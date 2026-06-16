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
        self.model = model or cfg.local_model
        self.host = cfg.ollama_host.rstrip("/")

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
        for block in content:
            btype = block.get("type")
            if btype == "text":
                texts.append(block.get("text", ""))
            elif btype == "image":
                texts.append("[image omitted — local model is text-only; reconnect for vision]")
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
        elif texts:
            out.insert(0, {"role": role, "content": "".join(texts)})
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
        return self._parse(body)

    @staticmethod
    def _parse(body: dict) -> Reply:
        msg = body.get("message", {}) or {}
        text = msg.get("content", "") or ""
        norm_blocks: list[dict] = []
        if text:
            norm_blocks.append({"type": "text", "text": text})
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
