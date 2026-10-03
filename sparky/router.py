"""Sends each request to the active model and copes when it cannot run.

The router holds the active model, asks the manager what that model can do
(only tool-capable models are offered tools; only thinking models get the
`think` switch), and when a model fails to load on this computer (usually
not enough memory) it retries once on the next smaller installed model, so
the turn still finishes.
"""

from __future__ import annotations

from .models import ModelManager
from .providers.base import ModelNotFound, ProviderError, Reply
from .providers.local import LocalProvider


class Router:
    def __init__(self, cfg, local: LocalProvider | None = None, manager: ModelManager | None = None):
        self.cfg = cfg
        self.manager = manager or ModelManager(cfg)
        self.local = local if local is not None else LocalProvider(cfg)
        self.model = self.manager.default()
        self.think = bool(getattr(cfg, "think", False))
        self.backend = "?"            # the model that served the last call
        self.last_fallback = False    # True when the last call fell back to a smaller model
        self.fallback_from = ""

    # ---- selection --------------------------------------------------------------
    def set_model(self, name: str) -> str | None:
        """Switch to an installed model by (forgiving) name. Returns the tag, or None."""
        hit = self.manager.resolve(name)
        if hit:
            self.model = hit
        return hit

    def cycle(self) -> str:
        self.model = self.manager.next_after(self.model)
        return self.model

    def supports(self, capability: str, model: str | None = None) -> bool:
        return capability in self.manager.capabilities(model or self.model)

    def _think_value(self, model: str):
        """None leaves the model's default; otherwise on/off. gpt-oss cannot
        switch reasoning off, only down, so it gets a level instead."""
        if not self.supports("thinking", model):
            return None
        if model.startswith("gpt-oss"):
            return "medium" if self.think else "low"
        return bool(self.think)

    # ---- serving ------------------------------------------------------------------
    def _serve(self, method: str, messages, tools, system, **kw) -> tuple[Reply, str]:
        self.last_fallback = False
        self.fallback_from = ""
        on_text = kw.pop("on_text", None)
        streamed = {"any": False}

        def guard(delta):
            # if a model dies after text has streamed, retrying elsewhere would
            # print a second, different start to the same reply
            streamed["any"] = True
            if on_text:
                on_text(delta)

        candidates = [self.model] + self.manager.smaller_than(self.model)
        last_err: ProviderError | None = None
        for i, model in enumerate(candidates[:2]):
            try:
                reply = self._call(method, model, messages, tools, system, guard, **kw)
            except ModelNotFound:
                raise
            except ProviderError as e:
                if streamed["any"] or "cannot reach" in str(e):
                    raise
                last_err = e
                continue
            if i:
                self.last_fallback = True
                self.fallback_from = self.model
            self.backend = model
            return reply, model
        raise last_err or ProviderError("no model could answer")

    def _call(self, method, model, messages, tools, system, on_text, **kw):
        self.local.set_model(model)
        use_tools = tools if (tools and self.supports("tools", model)) else None
        think = self._think_value(model)
        if method == "chat_stream":
            return self.local.chat_stream(messages, tools=use_tools, system=system,
                                          on_text=on_text, think=think, **kw)
        return self.local.chat(messages, tools=use_tools, system=system, think=think)

    def chat(self, messages, tools=None, system=None) -> tuple[Reply, str]:
        return self._serve("chat", messages, tools, system)

    def chat_stream(self, messages, tools=None, system=None, on_text=None, on_think=None,
                    cancel=None) -> tuple[Reply, str]:
        return self._serve("chat_stream", messages, tools, system, on_text=on_text,
                           on_think=on_think, cancel=cancel)

    def abort(self) -> None:
        self.local.abort()
