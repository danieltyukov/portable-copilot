"""Chat with the bundled Ollama server over stdlib HTTP.

Translates the normalized Anthropic-style message/block schema into Ollama's
/api/chat format and back, streams the reply, and reports token statistics.
"""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request

from .base import Cancelled, ModelNotFound, ProviderError, Reply, ToolCall

MAX_PREDICT = 2048


class LocalProvider:
    def __init__(self, cfg, model: str | None = None, ctx: int = 8192):
        self.cfg = cfg
        self.model = model or cfg.model
        self.host = cfg.ollama_host.rstrip("/")
        self.ctx = ctx
        self._active = None   # the response being streamed, so abort() can close it

    def set_model(self, model: str) -> None:
        self.model = model

    def abort(self) -> None:
        """Stop the reply in progress from another thread. A blocked read (the
        model still loading, say) only notices a cancel flag when the next
        chunk arrives; closing the socket ends the wait at once."""
        resp = self._active
        if resp is None:
            return
        # close() alone does not wake a read already blocked in recv();
        # shutting the socket down does, on every OS
        try:
            resp.fp.raw._sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            resp.close()
        except Exception:
            pass

    # ---- payload construction (pure; unit-tested) -----------------------
    def build_payload(self, messages: list[dict], tools, system: str | None,
                      think: bool | str | None = None) -> dict:
        ollama_messages: list[dict] = []
        if system:
            ollama_messages.append({"role": "system", "content": system})
        for msg in messages:
            ollama_messages.extend(self._translate_message(msg))
        # thinking spends tokens before the answer starts, so it gets more room
        predict = MAX_PREDICT * 3 if think else MAX_PREDICT
        payload: dict = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": False,
            "options": {"num_predict": min(predict, self.ctx // 2), "num_ctx": self.ctx},
        }
        if tools:
            payload["tools"] = [self._tool_to_ollama(t) for t in tools]
        if think is not None:
            payload["think"] = think
        return payload

    @staticmethod
    def _tool_to_ollama(spec: dict) -> dict:
        return {
            "type": "function",
            "function": {
                "name": spec["name"],
                "description": spec.get("description", ""),
                "parameters": spec.get("input_schema", {"type": "object", "properties": {}}),
            },
        }

    @staticmethod
    def _translate_message(msg: dict) -> list[dict]:
        """One normalized message -> one or more Ollama messages."""
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, str):
            return [{"role": role, "content": content}]

        out: list[dict] = []
        texts: list[str] = []
        tool_calls: list[dict] = []
        images: list[str] = []
        for block in content:
            btype = block.get("type")
            if btype == "text":
                texts.append(block.get("text", ""))
            elif btype == "image":
                # Ollama's `images` field; vision models read it, others ignore it.
                src = block.get("source", {}) or {}
                if src.get("data"):
                    images.append(src["data"])
            elif btype == "tool_use":
                tool_calls.append({
                    "function": {"name": block.get("name", ""), "arguments": block.get("input", {})}
                })
            elif btype == "tool_result":
                tc = block.get("content", "")
                if isinstance(tc, list):
                    tc = "".join(p.get("text", "") for p in tc if isinstance(p, dict))
                out.append({"role": "tool", "content": str(tc)})
        if role == "assistant":
            am: dict = {"role": "assistant", "content": "".join(texts)}
            if tool_calls:
                am["tool_calls"] = tool_calls
            out.insert(0, am)
        elif texts or images:
            m: dict = {"role": role, "content": "".join(texts)}
            if images:
                m["images"] = images
            out.insert(0, m)
        return out

    # ---- network --------------------------------------------------------
    def _open(self, payload: dict):
        req = urllib.request.Request(
            f"{self.host}/api/chat", data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"content-type": "application/json"},
        )
        try:
            # Loading a big model from a slow stick can take minutes before the
            # first token; the timeout is per read, so it only fires on a stall.
            return urllib.request.urlopen(req, timeout=900)
        except urllib.error.HTTPError as e:
            raise _http_error(e, self.model) from e
        except (urllib.error.URLError, OSError) as e:
            raise ProviderError(f"cannot reach the model server ({e})") from e

    def chat(self, messages: list[dict], tools=None, system: str | None = None,
             think: bool | str | None = None) -> Reply:
        payload = self.build_payload(messages, tools, system, think)
        try:
            with self._open(payload) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise ProviderError(f"model server error ({e})") from e
        tool_names = [t["name"] for t in tools] if tools else []
        return self._parse(body, tool_names)

    def chat_stream(self, messages: list[dict], tools=None, system: str | None = None,
                    on_text=None, on_think=None, think: bool | str | None = None,
                    cancel: threading.Event | None = None) -> Reply:
        """Stream /api/chat (NDJSON). on_text/on_think get each chunk.
        Setting `cancel` stops the reply and raises Cancelled; closing the
        connection also stops the server generating."""
        payload = self.build_payload(messages, tools, system, think)
        payload["stream"] = True
        texts: list[str] = []
        thoughts: list[str] = []
        raw_tool_calls: list[dict] = []
        final: dict = {}
        resp = self._active = self._open(payload)
        try:
            for raw in resp:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("error"):
                    raise ProviderError(str(ev["error"]))
                msg = ev.get("message", {}) or {}
                if msg.get("thinking"):
                    thoughts.append(msg["thinking"])
                    if on_think:
                        on_think(msg["thinking"])
                if msg.get("content"):
                    texts.append(msg["content"])
                    if on_text:
                        on_text(msg["content"])
                if msg.get("tool_calls"):
                    raw_tool_calls.extend(msg["tool_calls"])
                if ev.get("done"):
                    final = ev
        except (OSError, ValueError, AttributeError) as e:
            if cancel is not None and cancel.is_set():
                raise Cancelled() from e
            raise ProviderError(f"the model server stopped mid-reply ({e})") from e
        finally:
            self._active = None
            resp.close()
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        body = {"message": {"content": "".join(texts), "tool_calls": raw_tool_calls},
                **{k: v for k, v in final.items() if k != "message"}}
        tool_names = [t["name"] for t in tools] if tools else []
        reply = self._parse(body, tool_names)
        reply.thinking = "".join(thoughts)
        return reply

    @staticmethod
    def _parse(body: dict, tool_names=()) -> Reply:
        msg = body.get("message", {}) or {}
        text = msg.get("content", "") or ""
        tool_calls: list[ToolCall] = []
        for i, call in enumerate(msg.get("tool_calls", []) or []):
            fn = call.get("function", {}) or {}
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            tool_calls.append(ToolCall(id=f"call_{i}", name=fn.get("name", ""), input=args or {}))

        # Small models often write the tool call as JSON in their text instead
        # of using structured tool_calls. Recover it.
        if not tool_calls and tool_names:
            tool_calls, text = extract_text_tool_calls(text, tool_names)

        norm_blocks: list[dict] = []
        if text:
            norm_blocks.append({"type": "text", "text": text})
        for tc in tool_calls:
            norm_blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input})
        if not norm_blocks:
            norm_blocks.append({"type": "text", "text": ""})
        return Reply(
            text=text,
            tool_calls=tool_calls,
            content_blocks=norm_blocks,
            stop_reason=body.get("done_reason"),
            raw=body,
            stats=stats_from(body),
        )


def stats_from(body: dict) -> dict:
    """Token counts and speed from the server's final chunk (durations in ns)."""
    tokens = int(body.get("eval_count") or 0)
    secs = (body.get("eval_duration") or 0) / 1e9
    if tokens < 2 or secs < 0.01:
        return {}   # a one-token reply has no meaningful speed
    return {
        "tokens": tokens,
        "prompt_tokens": int(body.get("prompt_eval_count") or 0),
        "seconds": round(secs, 2),
        "tps": round(tokens / secs, 1) if secs else 0.0,
    }


def _http_error(e: urllib.error.HTTPError, model: str) -> ProviderError:
    detail = e.read().decode("utf-8", "replace")
    try:
        detail = json.loads(detail).get("error", detail)
    except (json.JSONDecodeError, AttributeError):
        pass
    detail = str(detail)[:300]
    if e.code == 404 or "not found" in detail.lower():
        return ModelNotFound(f"{model} is not on this stick")
    return ProviderError(f"model server error {e.code}: {detail}")


def extract_text_tool_calls(text: str, tool_names) -> tuple[list[ToolCall], str]:
    """Recover tool calls a small model emitted as JSON in its text.

    Handles ```json {...}``` fences, <tool_call>{...}</tool_call> tags, and bare
    objects like {"name": "list_dir", "arguments": {...}}. Returns the recovered
    calls and the text with those JSON blobs removed.
    """
    names = set(tool_names)
    if not text or not names:
        return [], text
    decoder = json.JSONDecoder()
    calls: list[ToolCall] = []
    spans: list[tuple[int, int]] = []
    i = 0
    n = len(text)
    while i < n:
        j = text.find("{", i)
        if j == -1:
            break
        try:
            obj, end = decoder.raw_decode(text, j)
        except json.JSONDecodeError:
            i = j + 1
            continue
        if isinstance(obj, dict) and obj.get("name") in names:
            args = obj.get("arguments")
            if args is None:
                args = obj.get("parameters")
            if args is None:
                args = {k: v for k, v in obj.items() if k != "name"}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            calls.append(ToolCall(id=f"call_{len(calls)}", name=obj["name"], input=args or {}))
            spans.append((j, end))
        i = end
    if not calls:
        return [], text
    cleaned = text
    for start, end in reversed(spans):
        cleaned = cleaned[:start] + cleaned[end:]
    cleaned = cleaned.replace("```json", "").replace("```", "")
    cleaned = cleaned.replace("<tool_call>", "").replace("</tool_call>", "")
    return calls, cleaned.strip()
