"""Configuration + path resolution for Sparky.

Everything Sparky needs lives on the stick. `data/sparky.env` holds the API key
and settings; this module resolves the stick root and merges env-file values
with process environment overrides.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Online default is Sonnet (fast + cheap for a portable copilot); Opus is
# selectable in-session via /model. Offline default is the bundled coder model.
DEFAULT_MODEL = "claude-sonnet-4-6"
OPUS_MODEL = "claude-opus-4-8"
DEFAULT_LOCAL_MODEL = "qwen2.5-coder:3b"
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"


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


@dataclass
class Config:
    root: Path
    data_dir: Path
    context_dir: Path
    runtime_dir: Path
    sessions_dir: Path
    env_file: Path
    anthropic_api_key: str | None
    model: str
    opus_model: str
    local_model: str
    yolo: bool
    ollama_host: str
    env: dict = field(default_factory=dict)


def find_root() -> Path:
    """The stick root = SPARKY_ROOT, else the parent of this package dir."""
    env_root = os.environ.get("SPARKY_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    return Path(__file__).resolve().parent.parent


def load(root: Path | None = None) -> Config:
    root = (root or find_root()).resolve()
    data_dir = root / "data"
    env_file = data_dir / "sparky.env"
    file_env = _parse_env_file(env_file)

    def pick(key: str, default: str | None = None) -> str | None:
        # process env wins over the on-stick env file
        return os.environ.get(key) or file_env.get(key) or default

    key = pick("ANTHROPIC_API_KEY")
    yolo_raw = pick("SPARKY_YOLO", "0") or "0"
    return Config(
        root=root,
        data_dir=data_dir,
        context_dir=root / "context",
        runtime_dir=root / "runtime",
        sessions_dir=data_dir / "sessions",
        env_file=env_file,
        anthropic_api_key=key or None,
        model=pick("SPARKY_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL,
        opus_model=pick("SPARKY_OPUS_MODEL", OPUS_MODEL) or OPUS_MODEL,
        local_model=pick("SPARKY_LOCAL_MODEL", DEFAULT_LOCAL_MODEL) or DEFAULT_LOCAL_MODEL,
        yolo=yolo_raw.lower() in ("1", "true", "yes", "on"),
        ollama_host=pick("OLLAMA_HOST", DEFAULT_OLLAMA_HOST) or DEFAULT_OLLAMA_HOST,
        env=file_env,
    )


def write_env(cfg: Config, updates: dict[str, str]) -> None:
    """Merge updates into data/sparky.env and chmod 600. Creates data/ if needed."""
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    merged = dict(_parse_env_file(cfg.env_file))
    merged.update(updates)
    lines = ["# Sparky settings — keep this file private (contains your API key)."]
    lines += [f"{k}={v}" for k, v in merged.items()]
    cfg.env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(cfg.env_file, 0o600)
    except OSError:
        pass
