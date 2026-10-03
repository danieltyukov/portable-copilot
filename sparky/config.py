"""Settings and paths.

Everything Sparky needs lives next to the app: on the stick, or in the folder
it was installed to. `data/sparky.env` holds the settings; process
environment variables override it, so a launcher or a user can change one
thing for a single run.

Settings (all optional):
    SPARKY_MODEL    the model to open with; empty means "best one installed"
    SPARKY_MODE     chat, code, write or study
    SPARKY_CTX      context window in tokens; 0 means "pick from this computer's memory"
    SPARKY_THINK    1 to show the reasoning of models that think before answering
    SPARKY_YOLO     1 to run shell commands without asking (code mode)

Sticks set up before 0.4 used two "tiers"; SPARKY_FAST_MODEL, SPARKY_MAX_MODEL
and SPARKY_TIER are still read so those sticks keep working.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import modes

# A non-default port so the bundled server never collides with an Ollama that
# the host computer may already be running on 11434.
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
        out[key.strip()] = val.split(" #")[0].strip().strip('"').strip("'")
    return out


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Config:
    root: Path
    data_dir: Path
    context_dir: Path
    runtime_dir: Path
    sessions_dir: Path
    env_file: Path
    model: str              # requested model; "" = choose from what is installed
    mode: str
    ctx: int                # 0 = automatic
    think: bool
    yolo: bool
    ollama_host: str
    legacy_fast: str = ""   # pre-0.4 tier models, used as aliases "fast" / "max"
    legacy_max: str = ""
    env: dict = field(default_factory=dict)

    @property
    def models_dir(self) -> Path:
        return self.runtime_dir / "ollama" / "models"


def find_root() -> Path:
    """The install root: SPARKY_ROOT, else the folder that holds the sparky package."""
    env_root = os.environ.get("SPARKY_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    return Path(__file__).resolve().parent.parent


def load(root: Path | str | None = None) -> Config:
    root = (Path(root) if root else find_root()).resolve()
    data_dir = root / "data"
    env_file = data_dir / "sparky.env"
    file_env = _parse_env_file(env_file)

    def pick(key: str, default: str = "") -> str:
        # the process environment wins over the file on the stick
        return os.environ.get(key) or file_env.get(key) or default

    legacy_fast = pick("SPARKY_FAST_MODEL")
    legacy_max = pick("SPARKY_MAX_MODEL")
    model = pick("SPARKY_MODEL")
    if not model and (legacy_fast or legacy_max):
        model = legacy_fast if pick("SPARKY_TIER").lower() in ("fast", "haiku") else legacy_max
        model = model or legacy_fast or legacy_max

    try:
        ctx = max(int(pick("SPARKY_CTX", "0")), 0)
    except ValueError:
        ctx = 0

    # The launcher sets OLLAMA_HOST in Ollama's own "host:port" form; the HTTP
    # client needs a full URL.
    host = pick("OLLAMA_HOST", DEFAULT_OLLAMA_HOST)
    if not host.startswith(("http://", "https://")):
        host = "http://" + host

    return Config(
        root=root,
        data_dir=data_dir,
        context_dir=root / "context",
        runtime_dir=root / "runtime",
        sessions_dir=data_dir / "sessions",
        env_file=env_file,
        model=model,
        mode=modes.resolve(pick("SPARKY_MODE")) or modes.DEFAULT_MODE,
        ctx=ctx,
        think=_truthy(pick("SPARKY_THINK")),
        yolo=_truthy(pick("SPARKY_YOLO")),
        ollama_host=host,
        legacy_fast=legacy_fast,
        legacy_max=legacy_max,
        env=file_env,
    )


def write_env(cfg: Config, updates: dict[str, str], remove: tuple[str, ...] = ()) -> None:
    """Merge updates into data/sparky.env (creating it), dropping `remove` keys."""
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    merged = {k: v for k, v in _parse_env_file(cfg.env_file).items() if k not in remove}
    merged.update(updates)
    lines = ["# Sparky settings. Everything runs on this computer; there are no keys to add."]
    lines += [f"{k}={v}" for k, v in merged.items()]
    cfg.env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(cfg.env_file, 0o600)
    except OSError:
        pass
    cfg.env.update(updates)


def context_window(cfg: Config, ram_gb: float) -> int:
    """Tokens of context to ask the server for. Ollama's own default is small
    (4096 on a CPU), which silently cuts off long conversations and the
    context folder, so Sparky always sets it."""
    if cfg.ctx:
        return cfg.ctx
    if ram_gb >= 24:
        return 16384
    return 8192
