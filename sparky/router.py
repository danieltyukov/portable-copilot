"""Tier router — Sparky's speed/accuracy switch over the local Qwen backend.

Sparky is fully local. The router holds the active *tier* (`fast` or `max`),
points the local provider at that tier's model, and serves the call. If the
`max` model can't be loaded on this host (typically not enough RAM), it
downgrades to `fast` for that call so the turn still completes — the local
analogue of the old online→offline fallback.
"""

from __future__ import annotations

from . import config as config_mod
from .providers.base import ProviderError, Reply
from .providers.local import LocalProvider


class Router:
    def __init__(self, cfg, local: LocalProvider | None = None):
        self.cfg = cfg
        self.local = local if local is not None else LocalProvider(cfg)
        self.tier = config_mod.normalize_tier(getattr(cfg, "tier", None))
        self.backend = "?"          # label of the backend that served the last call
        self.last_fallback = False  # True when the last call downgraded max→fast

    # ---- tier selection -------------------------------------------------
    def set_tier(self, tier: str) -> str:
        """Select 'fast'/'max' (aliases allowed). Returns the resolved tier."""
        self.tier = config_mod.normalize_tier(tier, self.tier)
        return self.tier

    def _model(self, tier: str) -> str:
        return self.cfg.model_for_tier(tier)

    def _serve(self, method: str, messages, tools, system, on_text=None) -> tuple[Reply, str]:
        """Run `method` ('chat'/'chat_stream') on the active tier; on a max
        load failure, downgrade to fast and retry once."""
        self.last_fallback = False
        tier = self.tier
        # Track whether any text streamed: if max dies mid-stream we must NOT
        # retry on fast (it would re-render the partial text in the UI).
        streamed = {"any": False}

        def guard(delta):
            streamed["any"] = True
            if on_text:
                on_text(delta)

        self.local.set_model(self._model(tier))
        try:
            reply = self._call(method, messages, tools, system, guard)
        except ProviderError:
            if tier != "max" or streamed["any"]:
                raise
            # max couldn't be served (e.g. OOM) — fall back to the fast tier.
            self.last_fallback = True
            self.local.set_model(self._model("fast"))
            reply = self._call(method, messages, tools, system, guard)
        self.backend = f"qwen:{self.local.model}" + (" (downgraded)" if self.last_fallback else "")
        return reply, self.backend

    def _call(self, method: str, messages, tools, system, on_text):
        if method == "chat_stream":
            return self.local.chat_stream(messages, tools=tools, system=system, on_text=on_text)
        return self.local.chat(messages, tools=tools, system=system)

    def chat(self, messages, tools=None, system=None) -> tuple[Reply, str]:
        """Returns (reply, backend_label)."""
        return self._serve("chat", messages, tools, system)

    def chat_stream(self, messages, tools=None, system=None, on_text=None) -> tuple[Reply, str]:
        """Streaming variant. Returns (reply, backend_label); on_text(delta) per chunk."""
        return self._serve("chat_stream", messages, tools, system, on_text=on_text)
