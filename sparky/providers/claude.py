"""Claude provider — talks to the Anthropic Messages API over stdlib HTTP.

No SDK dependency (avoids pydantic-core, a per-OS binary wheel) so the whole app
stays pure-Python and one `runtime/pylib` works across Linux/Mac/Windows.
"""

from __future__ import annotations

import json
import socket
import ssl
import urllib.error
import urllib.request

from .base import ProviderError, Reply, ToolCall

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
MAX_TOKENS = 8192


class ClaudeProvider:
    def __init__(self, cfg, model: str | None = None):
        self.cfg = cfg
        self.model = model or cfg.model

    # ---- payload construction (pure; unit-tested) -----------------------
    def build_payload(self, messages: list[dict], tools, system: str | None) -> dict:
        payload: dict = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "messages": messages,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = list(tools)
        return payload

    # ---- network --------------------------------------------------------
    def reachable(self, timeout: float = 3.0) -> bool:
        try:
            with socket.create_connection(("api.anthropic.com", 443), timeout=timeout):
                return True
        except OSError:
            return False

    def _request(self, payload: dict):
        if not self.cfg.anthropic_api_key:
            raise ProviderError("no Anthropic API key configured")
        data = json.dumps(payload).encode("utf-8")
        return urllib.request.Request(
            API_URL, data=data, method="POST",
            headers={
                "content-type": "application/json",
                "x-api-key": self.cfg.anthropic_api_key,
                "anthropic-version": API_VERSION,
            },
        )

    def chat(self, messages: list[dict], tools=None, system: str | None = None) -> Reply:
        payload = self.build_payload(messages, tools, system)
        req = self._request(payload)
        try:
            with urllib.request.urlopen(req, timeout=120, context=ssl.create_default_context()) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            raise ProviderError(f"Claude API HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise ProviderError(f"Claude API connection error: {e}") from e
        return self._parse(body)

    def chat_stream(self, messages: list[dict], tools=None, system: str | None = None,
                    on_text=None) -> Reply:
        """Stream the Messages API (SSE). Calls on_text(delta) for each text chunk
        and returns the final Reply (with any tool_use blocks assembled)."""
        payload = self.build_payload(messages, tools, system)
        payload["stream"] = True
        req = self._request(payload)
        texts: list[str] = []
        tool_calls: list[ToolCall] = []
        blocks: dict[int, dict] = {}      # index -> {type, id, name, buf/text}
        stop_reason = None
        try:
            with urllib.request.urlopen(req, timeout=300, context=ssl.create_default_context()) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    try:
                        ev = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    etype = ev.get("type")
                    if etype == "content_block_start":
                        cb = ev.get("content_block", {})
                        blocks[ev["index"]] = {"type": cb.get("type"), "id": cb.get("id"),
                                               "name": cb.get("name"), "buf": "", "text": ""}
                    elif etype == "content_block_delta":
                        b = blocks.get(ev["index"])
                        if not b:
                            continue
                        d = ev.get("delta", {})
                        if d.get("type") == "text_delta":
                            t = d.get("text", "")
                            b["text"] += t
                            texts.append(t)
                            if on_text:
                                on_text(t)
                        elif d.get("type") == "input_json_delta":
                            b["buf"] += d.get("partial_json", "")
                    elif etype == "message_delta":
                        stop_reason = ev.get("delta", {}).get("stop_reason", stop_reason)
                    elif etype == "error":
                        raise ProviderError(f"Claude stream error: {ev.get('error')}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            raise ProviderError(f"Claude API HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise ProviderError(f"Claude API connection error: {e}") from e

        norm_blocks: list[dict] = []
        for idx in sorted(blocks):
            b = blocks[idx]
            if b["type"] == "text":
                norm_blocks.append({"type": "text", "text": b["text"]})
            elif b["type"] == "tool_use":
                try:
                    inp = json.loads(b["buf"]) if b["buf"].strip() else {}
                except json.JSONDecodeError:
                    inp = {}
                tc = ToolCall(id=b["id"], name=b["name"], input=inp)
                tool_calls.append(tc)
                norm_blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input})
        if not norm_blocks:
            norm_blocks.append({"type": "text", "text": ""})
        return Reply(text="".join(texts), tool_calls=tool_calls,
                     content_blocks=norm_blocks, stop_reason=stop_reason)

    @staticmethod
    def _parse(body: dict) -> Reply:
        blocks = body.get("content", []) or []
        texts: list[str] = []
        tool_calls: list[ToolCall] = []
        norm_blocks: list[dict] = []
        for b in blocks:
            btype = b.get("type")
            if btype == "text":
                texts.append(b.get("text", ""))
                norm_blocks.append({"type": "text", "text": b.get("text", "")})
            elif btype == "tool_use":
                tc = ToolCall(id=b.get("id", ""), name=b.get("name", ""), input=b.get("input", {}) or {})
                tool_calls.append(tc)
                norm_blocks.append({
                    "type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input,
                })
        stop = body.get("stop_reason")
        if stop == "refusal" and not texts:
            texts.append("[Claude declined this request for safety reasons.]")
            norm_blocks.append({"type": "text", "text": texts[-1]})
        if not norm_blocks:
            norm_blocks.append({"type": "text", "text": ""})
        return Reply(
            text="".join(texts),
            tool_calls=tool_calls,
            content_blocks=norm_blocks,
            stop_reason=stop,
            raw=body,
        )
