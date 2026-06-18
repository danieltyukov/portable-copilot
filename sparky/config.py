"""Configuration + path resolution for Sparky.

Everything Sparky needs lives on the stick. `data/sparky.env` holds settings;
this module resolves the stick root and merges env-file values with process
environment overrides.

Sparky is fully local: it runs Qwen models via a bundled Ollama and lets you
switch between speed/accuracy *tiers* (the local analogue of Haiku ↔ Opus).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Two tiers, chosen to fit "any laptop + ~29 GB stick" (CPU inference):
#   fast → a small, snappy model that runs anywhere.
#   max  → a 30B a3b MoE (~3B active) — the best CPU agentic coder that fits.
# `max` is the default so Sparky opens on the strongest model; it auto-downgrades
# to `fast` at the router if a host can't load it (see router.py).
DEFAULT_FAST_MODEL = "qwen3.5:4b"
DEFAULT_MAX_MODEL = "qwen3-coder:30b"
DEFAULT_TIER = "max"

# Friendly aliases so Claude-Code muscle memory keeps working with /model.
TIER_ALIASES = {"haiku": "fast", "sonnet": "max", "opus": "max", "f": "fast", "m": "max"}

# A non-default port so the bundled Ollama never collides with a system Ollama
# that may already own 11434 on the host machine.
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11500"


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE env file. Ignores blanks and # comments."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def normalize_tier(name: str | None, default: str = DEFAULT_TIER) -> str:
    """Resolve a user-typed tier name (incl. aliases) to 'fast' or 'max'."""
    if not name:
        return default
    n = name.strip().lower()
    n = TIER_ALIASES.get(n, n)
    return n if n in ("fast", "max") else default


@dataclass
class Config:
    root: Path
    data_dir: Path
    context_dir: Path
    runtime_dir: Path
    sessions_dir: Path
    env_file: Path
    fast_model: str
    max_model: str
    tier: str
    yolo: bool
    ollama_host: str
    env: dict = field(default_factory=dict)

    @property
    def tiers(self) -> list[tuple[str, str]]:
        """Ordered (tier_name, model) pairs — drives the Ctrl-T cycle order."""
        return [("fast", self.fast_model), ("max", self.max_model)]

    def model_for_tier(self, tier: str | None = None) -> str:
        return self.max_model if normalize_tier(tier, self.tier) == "max" else self.fast_model

    @property
    def model(self) -> str:
        """The model for the currently-selected tier."""
        return self.model_for_tier(self.tier)


def find_root() -> Path:
    """The stick root = SPARKY_ROOT, else the parent of this package dir."""
    env_root = os.environ.get("SPARKY_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    return Path(__file__).resolve().parent.parent


def load(root: Path | str | None = None) -> Config:
    root = (Path(root) if root else find_root()).resolve()
    data_dir = root / "data"
    env_file = data_dir / "sparky.env"
    file_env = _parse_env_file(env_file)

    def pick(key: str, default: str | None = None) -> str | None:
        # process env wins over the on-stick env file
        return os.environ.get(key) or file_env.get(key) or default

    yolo_raw = pick("SPARKY_YOLO", "0") or "0"
    # OLLAMA_HOST is set by the launcher in ollama's own "host:port" form (no
    # scheme); our stdlib HTTP client needs a full URL, so normalize it.
    ollama_host = pick("OLLAMA_HOST", DEFAULT_OLLAMA_HOST) or DEFAULT_OLLAMA_HOST
    if not ollama_host.startswith(("http://", "https://")):
        ollama_host = "http://" + ollama_host
    return Config(
        root=root,
        data_dir=data_dir,
        context_dir=root / "context",
        runtime_dir=root / "runtime",
        sessions_dir=data_dir / "sessions",
        env_file=env_file,
        fast_model=pick("SPARKY_FAST_MODEL", DEFAULT_FAST_MODEL) or DEFAULT_FAST_MODEL,
        max_model=pick("SPARKY_MAX_MODEL", DEFAULT_MAX_MODEL) or DEFAULT_MAX_MODEL,
        tier=normalize_tier(pick("SPARKY_TIER", DEFAULT_TIER)),
        yolo=yolo_raw.lower() in ("1", "true", "yes", "on"),
        ollama_host=ollama_host,
        env=file_env,
    )


def write_env(cfg: Config, updates: dict[str, str]) -> None:
    """Merge updates into data/sparky.env and chmod 600. Creates data/ if needed."""
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    merged = dict(_parse_env_file(cfg.env_file))
    merged.update(updates)
    lines = ["# Sparky settings — fully local, no API keys needed."]
    lines += [f"{k}={v}" for k, v in merged.items()]
    cfg.env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(cfg.env_file, 0o600)
    except OSError:
        pass
