"""Loads the per-drive `context/` drop folder into the system prompt.

Whatever the user drops into Sparky/context/ on the stick is auto-fed to the
copilot every session: a file tree plus the (budgeted) text of small files.
"""

from __future__ import annotations

from pathlib import Path

MAX_TOTAL = 60_000        # cap total context bytes
MAX_PER_FILE = 12_000
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

    tree_lines = [str(p.relative_to(context_dir)) for p in files]
    parts = ["The user has dropped these files into the drive's context/ folder:",
             "\n".join(f"  - {t}" for t in tree_lines), ""]

    total = sum(len(s) for s in parts)
    for p in files:
        if total >= MAX_TOTAL:
            parts.append("…[context budget reached; remaining files listed above only]")
            break
        rel = p.relative_to(context_dir)
        if not _is_texty(p):
            parts.append(f"### {rel} (binary — skipped)")
            continue
        try:
            body = p.read_text(encoding="utf-8", errors="strict")[:MAX_PER_FILE]
        except (UnicodeDecodeError, OSError):
            parts.append(f"### {rel} (unreadable — skipped)")
            continue
        chunk = f"### {rel}\n{body}"
        parts.append(chunk)
        total += len(chunk)
    return "\n\n".join(parts)
