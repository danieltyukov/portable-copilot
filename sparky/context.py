"""Loads the per-drive `context/` drop folder into the system prompt.

Whatever the user drops into Sparky/context/ on the stick is auto-fed to the
copilot every session: a file tree plus the (budgeted) text of small files.
"""

from __future__ import annotations

from pathlib import Path

MAX_TOTAL = 400_000       # cap total context bytes (~100K tokens) sent each turn
MAX_PER_FILE = 200_000
MAX_LISTED = 60           # cap the file-tree listing so attachment dumps don't flood
TEXT_SUFFIXES = {
    ".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".sh", ".bash", ".html", ".css", ".c", ".h", ".cpp",
    ".go", ".rs", ".java", ".rb", ".php", ".sql", ".env", ".csv", ".xml", ".rst",
}
SKIP_NAMES = {"README.txt"}  # the seeded instructions file


def _is_texty(p: Path) -> bool:
    return p.suffix.lower() in TEXT_SUFFIXES or p.suffix == ""


def load_context(context_dir: Path) -> str:
    if not context_dir.exists():
        return ""
    files = sorted(p for p in context_dir.rglob("*") if p.is_file())
    files = [p for p in files if p.name not in SKIP_NAMES and not p.name.startswith(".")]
    if not files:
        return ""

    base = context_dir.resolve()
    tree_lines = [str(p.relative_to(context_dir)) for p in files]
    shown = tree_lines[:MAX_LISTED]
    if len(tree_lines) > MAX_LISTED:
        shown.append(f"… (+{len(tree_lines) - MAX_LISTED} more files)")
    parts = [
        f"The user has dropped reference files into this drive's context folder ({base}).",
        "Their text is included below (up to a budget). For ANY file here — including "
        "ones not shown inline below or marked (not loaded) — you can open the full "
        f"content yourself with the read_file or search tools using its absolute path "
        f"under {base}.",
        "Files:",
        "\n".join(f"  - {t}" for t in shown), "",
    ]

    total = sum(len(s) for s in parts)
    for p in files:
        rel = p.relative_to(context_dir)
        if not _is_texty(p):
            continue  # binaries (pdf/png) are listed above; not inlined
        if total >= MAX_TOTAL:
            parts.append(f"### {rel} (not loaded — over budget; read it with read_file at {base / rel})")
            continue
        try:
            body = p.read_text(encoding="utf-8", errors="strict")[:MAX_PER_FILE]
        except (UnicodeDecodeError, OSError):
            continue
        chunk = f"### {rel}\n{body}"
        parts.append(chunk)
        total += len(chunk)
    return "\n\n".join(parts)
