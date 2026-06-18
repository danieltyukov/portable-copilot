"""The agent loop — multi-step tool use over the router.

`run_turn` sends the conversation through the router; if the model asks for
tools, it runs them, appends the results, and loops until the model returns a
final text answer. Emits events so the UI can render text and tool activity.
"""

from __future__ import annotations

from pathlib import Path

from . import tools as tools_mod
from .context import load_context
from .router import Router

MAX_ITERS = 12

SYSTEM_BASE = (
    "You are Sparky, a portable AI coding copilot that runs fully locally from a "
    "USB stick on a local Qwen model (no internet, nothing leaves the machine). "
    "You help with software engineering tasks: reading and editing files, running "
    "commands, searching code, and answering questions. Use the provided tools to "
    "inspect and modify the project. Be concise and act directly. The working "
    "directory is the folder the user launched you in."
)


class Agent:
    def __init__(self, cfg, router: Router, cwd: Path | None = None):
        self.cfg = cfg
        self.router = router
        self.cwd = cwd or Path.cwd()
        self.history: list[dict] = []

    def system_prompt(self) -> str:
        ctx = load_context(self.cfg.context_dir)
        parts = [SYSTEM_BASE, f"Working directory: {self.cwd}"]
        if ctx:
            parts.append("--- Drive context (dropped by the user) ---\n" + ctx)
        return "\n\n".join(parts)

    def run_turn(self, user_text: str, images: list[dict] | None = None, on_event=None) -> str:
        """Run one user turn to completion. Returns the final assistant text."""
        def emit(kind, **data):
            if on_event:
                on_event(kind, data)

        content: list[dict] = []
        for img in images or []:
            content.append(img)
        content.append({"type": "text", "text": user_text})
        self.history.append({"role": "user", "content": content})

        system = self.system_prompt()
        final_text = ""
        for _ in range(MAX_ITERS):
            emit("thinking")
            reply, backend = self.router.chat_stream(
                self.history, tools=tools_mod.TOOL_SPECS, system=system,
                on_text=lambda t: emit("assistant_delta", text=t),
            )
            emit("backend", backend=backend, fallback=self.router.last_fallback)
            self.history.append({"role": "assistant", "content": reply.content_blocks})
            emit("assistant_done", text=reply.text)
            if not reply.wants_tools:
                final_text = reply.text
                break
            results: list[dict] = []
            for tc in reply.tool_calls:
                emit("tool_start", name=tc.name, input=tc.input)
                output = tools_mod.run_tool(tc.name, tc.input, cwd=self.cwd, confirm=self._confirm(on_event))
                emit("tool_result", name=tc.name, output=output)
                results.append({"type": "tool_result", "tool_use_id": tc.id, "content": output})
            self.history.append({"role": "user", "content": results})
        else:
            final_text = "[Stopped after too many tool iterations.]"
            emit("assistant_done", text=final_text)
        return final_text

    def _confirm(self, on_event):
        if self.cfg.yolo:
            return lambda cmd: True

        def confirm(cmd: str) -> bool:
            if on_event:
                holder = {}
                on_event("confirm", {"command": cmd, "holder": holder})
                return bool(holder.get("approved"))
            return False

        return confirm
