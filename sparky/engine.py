"""Wires a conversation together: model manager, router, agent, sized to
this computer. Shared by the terminal UI, the browser UI and `ask`."""

from __future__ import annotations

from pathlib import Path

from . import config as config_mod
from . import hardware
from .agent import Agent
from .models import ModelManager
from .providers.local import LocalProvider
from .router import Router


def build(cfg, cwd: Path | None = None) -> Agent:
    ctx = config_mod.context_window(cfg, hardware.total_ram_gb())
    manager = ModelManager(cfg)
    router = Router(cfg, local=LocalProvider(cfg, ctx=ctx), manager=manager)
    return Agent(cfg, router, cwd=cwd or Path.cwd(), ctx_tokens=ctx)


def no_models_message(cfg) -> str:
    return ("There are no models on this stick yet. Add one while online, for example:\n"
            "  sparky.cmd models recommend          (see what fits this computer)\n"
            "  sparky.cmd models add qwen3.5:4b     (a good first model, 3.4 GB)")
