"""The stick's `context/` folder, fed to the model with every conversation.

Whatever is dropped into context/ is listed, and the text of as many files
as fit the budget is included. The budget comes from the context window, so a
big folder can never crowd the conversation out; files that do not fit are
still listed by name.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_MAX_CHARS = 40_000
MAX_LISTED = 60           # a long attachment dump should not flood the listing
TEXT_SUFFIXES = {
    ".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".sh", ".bash", ".html", ".css", ".c", ".h", ".cpp",
    ".go", ".rs", ".java", ".rb", ".php", ".sql", ".env", ".csv", ".xml", ".rst",
    ".tex", ".org", ".log",
}
SKIP_NAMES = {"README.txt"}  # the instructions file setup puts there


def _is_texty(p: Path) -> bool:
    return p.suffix.lower() in TEXT_SUFFIXES or p.suffix == ""


def list_files(context_dir: Path) -> list[Path]:
    if not context_dir.exists():
        return []
    files = sorted(p for p in context_dir.rglob("*") if p.is_file())
    return [p for p in files if p.name not in SKIP_NAMES
            and not any(part.startswith(".") for part in p.relative_to(context_dir).parts)]


def load_context(context_dir: Path, max_chars: int = DEFAULT_MAX_CHARS, can_read: bool = True) -> str:
    files = list_files(context_dir)
    if not files:
        return ""

    base = context_dir.resolve()
    names = [str(p.relative_to(context_dir)) for p in files]
    shown = names[:MAX_LISTED]
    if len(names) > MAX_LISTED:
        shown.append(f"(and {len(names) - MAX_LISTED} more files)")
    intro = f"The user keeps reference files in {base}. Their text is included below, up to a budget."
    if can_read:
        intro += (" Any file listed, including ones marked (not loaded), can be opened with "
                  f"read_file or searched with search using its path under {base}.")
    else:
        intro += (" Files marked (not loaded) did not fit; if a question needs one, say so and "
                  "suggest the Study mode, which can open them.")
    parts = [intro, "Files:", "\n".join(f"  - {t}" for t in shown), ""]

    total = sum(len(s) for s in parts)
    for p in files:
        rel = p.relative_to(context_dir)
        if not _is_texty(p):
            continue  # PDFs and images are listed above but not inlined
        try:
            body = p.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            continue
        room = max_chars - total
        if room < 400:
            parts.append(f"### {rel} (not loaded)")
            continue
        if len(body) > room - 100:
            body = body[: room - 100] + "\n[...rest not loaded]"
        chunk = f"### {rel}\n{body}"
        parts.append(chunk)
        total += len(chunk)
    return "\n\n".join(parts)
