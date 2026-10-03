"""The turn loop: send the conversation, run any tools the model asks for,
repeat until it answers in text.

Emits events so a front end (terminal or browser) can show the reply as it
streams, each tool as it runs, and any approval it needs:

    thinking          the model has been asked; nothing back yet
    think_delta       reasoning text (models that think aloud)
    assistant_delta   reply text
    assistant_done    the full reply text for this step
    tool_start / tool_result
    confirm           {command, holder}; set holder["approved"]
    notice            {text}; e.g. it fell back to a smaller model
    stats             {model, tokens, tps, seconds}
"""

from __future__ import annotations

import threading
from pathlib import Path

from . import modes as modes_mod
from . import tools as tools_mod
from .context import load_context
from .providers.base import Cancelled

MAX_ITERS = 12
CHARS_PER_TOKEN = 3.5      # a conservative average for English and code
REPLY_RESERVE = 2048       # tokens kept free for the answer itself
OLD_TOOL_OUTPUT = 1500     # older tool results are cut to this many characters


class Agent:
    def __init__(self, cfg, router, cwd: Path | None = None, ctx_tokens: int = 8192):
        self.cfg = cfg
        self.router = router
        self.cwd = cwd or Path.cwd()
        self.mode = modes_mod.get(getattr(cfg, "mode", None)).id
        self.ctx_tokens = ctx_tokens
        self.history: list[dict] = []
        self.cancel = threading.Event()

    # ---- prompt ---------------------------------------------------------------------
    @property
    def mode_obj(self) -> modes_mod.Mode:
        return modes_mod.get(self.mode)

    def system_prompt(self) -> str:
        mode = self.mode_obj
        parts = [mode.prompt, f"Working directory: {self.cwd}"]
        # The context folder gets at most 40% of the window, so the
        # conversation always has room.
        budget = int(self.ctx_tokens * 0.4 * CHARS_PER_TOKEN)
        ctx = load_context(self.cfg.context_dir, max_chars=budget, can_read=bool(mode.tools))
        if ctx:
            parts.append("--- The user's context folder ---\n" + ctx)
        return "\n\n".join(parts)

    def tool_specs(self) -> list[dict]:
        allowed = set(self.mode_obj.tools)
        return [t for t in tools_mod.TOOL_SPECS if t["name"] in allowed]

    # ---- the turn -------------------------------------------------------------------
    def run_turn(self, user_text: str, images: list[dict] | None = None, on_event=None) -> str:
        """Run one user turn to completion and return the final text. If the
        user cancels, the unfinished turn is removed from history and
        Cancelled is raised."""
        def emit(kind, **data):
            if on_event:
                on_event(kind, data)

        self.cancel.clear()
        start = len(self.history)
        content: list[dict] = list(images or [])
        content.append({"type": "text", "text": user_text})
        self.history.append({"role": "user", "content": content})

        system = self.system_prompt()
        specs = self.tool_specs()
        budget = max(int((self.ctx_tokens - REPLY_RESERVE) * CHARS_PER_TOKEN) - len(system), 2000)
        final_text = ""
        try:
            for _ in range(MAX_ITERS):
                emit("thinking")
                reply, backend = self.router.chat_stream(
                    fit_history(self.history, budget), tools=specs or None, system=system,
                    on_text=lambda t: emit("assistant_delta", text=t),
                    on_think=lambda t: emit("think_delta", text=t),
                    cancel=self.cancel,
                )
                if self.router.last_fallback:
                    emit("notice", text=f"{self.router.fallback_from} would not load on this "
                                        f"computer (probably not enough memory), so {backend} answered.")
                self.history.append({"role": "assistant", "content": reply.content_blocks})
                emit("assistant_done", text=reply.text)
                if reply.stats:
                    emit("stats", model=backend, **reply.stats)
                if reply.thinking and not reply.text.strip() and not reply.wants_tools:
                    emit("notice", text="The model spent the whole reply thinking and gave no answer. "
                                        "Ask again, or turn thinking off (/think).")
                if not reply.wants_tools:
                    final_text = reply.text
                    break
                results: list[dict] = []
                for tc in reply.tool_calls:
                    if self.cancel.is_set():
                        raise Cancelled()
                    emit("tool_start", name=tc.name, input=tc.input)
                    if tc.name not in self.mode_obj.tools:
                        output = f"Error: the {tc.name} tool is not available in {self.mode} mode."
                    else:
                        output = tools_mod.run_tool(tc.name, tc.input, cwd=self.cwd,
                                                    confirm=self._confirm(on_event))
                    emit("tool_result", name=tc.name, output=output)
                    results.append({"type": "tool_result", "tool_use_id": tc.id, "content": output})
                self.history.append({"role": "user", "content": results})
            else:
                final_text = "[Stopped after too many tool steps. Ask again to continue.]"
                emit("assistant_done", text=final_text)
        except (Cancelled, KeyboardInterrupt):
            del self.history[start:]
            raise Cancelled() from None
        except Exception:
            # a failed turn must not leave a dangling user message behind, or
            # the next turn would be sent two questions in a row
            del self.history[start:]
            raise
        return final_text

    def stop(self) -> None:
        """Cancel the turn in progress (safe to call from another thread)."""
        self.cancel.set()
        abort = getattr(self.router, "abort", None)
        if abort:
            abort()

    def _confirm(self, on_event):
        if self.cfg.yolo:
            return lambda cmd: True

        def confirm(cmd: str) -> bool:
            if on_event:
                holder: dict = {}
                on_event("confirm", {"command": cmd, "holder": holder})
                return bool(holder.get("approved"))
            return False

        return confirm


def _size(msg: dict) -> int:
    c = msg.get("content")
    if isinstance(c, str):
        return len(c)
    n = 0
    for b in c or []:
        if b.get("type") == "text":
            n += len(b.get("text", ""))
        elif b.get("type") == "tool_result":
            n += len(str(b.get("content", "")))
        elif b.get("type") == "tool_use":
            n += len(str(b.get("input", ""))) + 40
        elif b.get("type") == "image":
            n += 3000   # vision models spend roughly a thousand tokens per image
    return n


def _is_question(msg: dict) -> bool:
    """A user message the person typed, as opposed to tool results."""
    if msg.get("role") != "user":
        return False
    c = msg.get("content")
    if isinstance(c, str):
        return True
    return any(b.get("type") in ("text", "image") for b in c or [])


def _shorten_tool_results(msg: dict) -> dict:
    c = msg.get("content")
    if not isinstance(c, list) or not any(b.get("type") == "tool_result" for b in c):
        return msg
    blocks = []
    for b in c:
        if b.get("type") == "tool_result":
            text = str(b.get("content", ""))
            if len(text) > OLD_TOOL_OUTPUT:
                b = {**b, "content": text[:OLD_TOOL_OUTPUT] + "\n[...cut to save space]"}
        blocks.append(b)
    return {**msg, "content": blocks}


def fit_history(history: list[dict], budget_chars: int) -> list[dict]:
    """The most recent part of the conversation that fits the budget.

    Older tool outputs are shortened first, then whole old turns are dropped.
    The result always starts at a question the user typed, so the model never
    sees a tool result without the call that produced it.
    """
    if not history:
        return []
    # the last question onwards is the turn in progress: never drop it
    starts = [i for i, m in enumerate(history) if _is_question(m)] or [0]
    current = starts[-1]
    msgs = [_shorten_tool_results(m) if i < current else m for i, m in enumerate(history)]
    total = sum(_size(m) for m in msgs)
    for s in starts:
        if total <= budget_chars or s == current:
            return msgs[s:]
        total -= sum(_size(m) for m in msgs[s:_next(starts, s, len(msgs))])
    return msgs[current:]


def _next(starts: list[int], s: int, end: int) -> int:
    later = [x for x in starts if x > s]
    return later[0] if later else end
