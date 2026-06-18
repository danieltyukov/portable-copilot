"""Local provider — talks to a bundled Ollama serving Qwen, over stdlib HTTP.

Translates the normalized Anthropic-style message/block schema into Ollama's
OpenAI-ish /api/chat format and back. Images are dropped with a note (the coder
model is text-only).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .base import ProviderError, Reply, ToolCall

MAX_PREDICT = 2048


class LocalProvider:
    def __init__(self, cfg, model: str | None = None):
        self.cfg = cfg
        self.model = model or cfg.model
        self.host = cfg.ollama_host.rstrip("/")

    def set_model(self, model: str) -> None:
        """Point this provider at a different Ollama model (used for tier switches)."""
        self.model = model

    # ---- payload construction (pure; unit-tested) -----------------------
    def build_payload(self, messages: list[dict], tools, system: str | None) -> dict:
        ollama_messages: list[dict] = []
        if system:
            ollama_messages.append({"role": "system", "content": system})
        for msg in messages:
            ollama_messages.extend(self._translate_message(msg))
        payload: dict = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": False,
            "options": {"num_predict": MAX_PREDICT},
        }
        if tools:
            payload["tools"] = [self._tool_to_ollama(t) for t in tools]
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
                # Pass to Ollama's `images` field — used if the local model has
                # vision (e.g. a qwen-vl); text-only models ignore it.
                src = block.get("source", {}) or {}
                if src.get("data"):
                    images.append(src["data"])
            elif btype == "tool_use":
                tool_calls.append({
                    "function": {"name": block.get("name", ""), "arguments": block.get("input", {})}
                })
            elif btype == "tool_result":
                # tool results become a dedicated Ollama "tool" message
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
    def reachable(self, timeout: float = 2.0) -> bool:
        try:
            req = urllib.request.Request(f"{self.host}/api/tags")
            with urllib.request.urlopen(req, timeout=timeout):
                return True
        except OSError:
            return False

    def chat(self, messages: list[dict], tools=None, system: str | None = None) -> Reply:
        payload = self.build_payload(messages, tools, system)
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.host}/api/chat", data=data, method="POST",
            headers={"content-type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise ProviderError(f"Ollama HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise ProviderError(f"Ollama connection error: {e}") from e
        tool_names = [t["name"] for t in tools] if tools else []
        return self._parse(body, tool_names)

    def chat_stream(self, messages: list[dict], tools=None, system: str | None = None,
                    on_text=None) -> Reply:
        """Stream Ollama /api/chat (NDJSON). Calls on_text(delta) per chunk."""
        payload = self.build_payload(messages, tools, system)
        payload["stream"] = True
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.host}/api/chat", data=data, method="POST",
            headers={"content-type": "application/json"},
        )
        texts: list[str] = []
        raw_tool_calls: list[dict] = []
        done_reason = None
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg = ev.get("message", {}) or {}
                    t = msg.get("content", "")
                    if t:
                        texts.append(t)
                        if on_text:
                            on_text(t)
                    if msg.get("tool_calls"):
                        raw_tool_calls.extend(msg["tool_calls"])
                    if ev.get("done"):
                        done_reason = ev.get("done_reason", done_reason)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise ProviderError(f"Ollama HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise ProviderError(f"Ollama connection error: {e}") from e
        body = {"message": {"content": "".join(texts), "tool_calls": raw_tool_calls},
                "done_reason": done_reason}
        tool_names = [t["name"] for t in tools] if tools else []
        return self._parse(body, tool_names)

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
            tc = ToolCall(id=f"call_{i}", name=fn.get("name", ""), input=args or {})
            tool_calls.append(tc)

        # Fallback: small models (e.g. qwen2.5-coder:3b) often emit the tool call
        # as a JSON blob in the text instead of structured tool_calls. Recover it.
        if not tool_calls and tool_names:
            extracted, text = extract_text_tool_calls(text, tool_names)
            tool_calls = extracted

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
        )

    def ensure_model(self) -> None:
        """Best-effort: trigger a pull if the model isn't present. Non-fatal."""
        try:
            data = json.dumps({"name": self.model}).encode("utf-8")
            req = urllib.request.Request(
                f"{self.host}/api/show", data=data, method="POST",
                headers={"content-type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5):
                return
        except OSError:
            return


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
    # strip the matched JSON (and surrounding ``` / <tool_call> wrappers) from text
    cleaned = text
    for start, end in reversed(spans):
        cleaned = cleaned[:start] + cleaned[end:]
    cleaned = cleaned.replace("```json", "").replace("```", "")
    cleaned = cleaned.replace("<tool_call>", "").replace("</tool_call>", "")
    return calls, cleaned.strip()
