"""Image handling — detect image paths in a prompt and base64-encode them into
normalized Anthropic image blocks. Uses only stdlib (no Pillow), so it stays
pure-Python and cross-OS.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# Match bare-ish paths ending in an image extension (quoted or unquoted).
_PATH_RE = re.compile(r"""['"]?([^\s'"]+\.(?:png|jpe?g|gif|webp))['"]?""", re.IGNORECASE)


def media_type(path: str | Path) -> str | None:
    return MEDIA_TYPES.get(Path(path).suffix.lower())


def find_image_paths(text: str, cwd: Path | None = None) -> list[str]:
    """Return image paths mentioned in `text` that actually exist on disk."""
    cwd = cwd or Path.cwd()
    found: list[str] = []
    for m in _PATH_RE.finditer(text):
        raw = m.group(1)
        p = Path(raw).expanduser()
        p = p if p.is_absolute() else (cwd / p)
        if p.is_file() and media_type(p):
            found.append(str(p))
    return found


def encode_image(path: str | Path) -> dict:
    """Return a normalized image content block for the given file."""
    p = Path(path).expanduser()
    mt = media_type(p)
    if not mt:
        raise ValueError(f"unsupported image type: {p.suffix}")
    data = base64.standard_b64encode(p.read_bytes()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": mt, "data": data}}
