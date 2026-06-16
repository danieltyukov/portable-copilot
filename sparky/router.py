"""Provider router — the heart of Sparky's online/offline switch.

`chat()` picks Claude when online and a key is present; on any provider error,
or when offline, it falls back to the local Qwen backend. The fallback is
per-call, so a turn that starts online and loses Wi-Fi still completes on Qwen.
"""

from __future__ import annotations

from .connectivity import Monitor
from .providers.base import ProviderError, Reply
from .providers.claude import ClaudeProvider
from .providers.local import LocalProvider


class Router:
    def __init__(self, cfg, monitor: Monitor | None = None,
                 claude: ClaudeProvider | None = None,
                 local: LocalProvider | None = None):
        self.cfg = cfg
        self.monitor = monitor or Monitor()
        self.claude = claude if claude is not None else ClaudeProvider(cfg)
        self.local = local if local is not None else LocalProvider(cfg)
        self.backend = "?"          # label of the backend that served the last call
        self.last_fallback = False  # True when the last call fell back to local

    def _can_use_claude(self) -> bool:
        return bool(self.cfg.anthropic_api_key) and self.monitor.online

    def chat(self, messages, tools=None, system=None) -> tuple[Reply, str]:
        """Returns (reply, backend_label)."""
        self.last_fallback = False
        if self._can_use_claude():
            try:
                reply = self.claude.chat(messages, tools=tools, system=system)
                self.backend = f"claude:{self.claude.model}"
                return reply, self.backend
            except ProviderError:
                # API failed mid-session — degrade to local for this call.
                self.monitor.refresh()
                self.last_fallback = True
        reply = self.local.chat(messages, tools=tools, system=system)
        self.backend = f"qwen:{self.local.model}" + (" (fallback)" if self.last_fallback else "")
        return reply, self.backend

    def set_online_model(self, model: str) -> None:
        self.claude.model = model
