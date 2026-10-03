"""Modes: how the assistant behaves, independent of which model runs it.

A mode is a system prompt plus the tools it may use. Small models answer
faster and more reliably with no tools offered, so only the modes that need
the filesystem get them.
"""

from __future__ import annotations

from dataclasses import dataclass

READ_TOOLS = ("read_file", "list_dir", "search")
ALL_TOOLS = ("read_file", "write_file", "edit_file", "list_dir", "search", "run_shell")


@dataclass(frozen=True)
class Mode:
    id: str
    label: str
    blurb: str
    prompt: str
    tools: tuple[str, ...] = ()


_BASE = (
    "You are Sparky, an assistant running entirely on this computer from a USB stick, "
    "on an open-weight model. Nothing the user types leaves the machine. "
)

MODES: dict[str, Mode] = {
    "chat": Mode(
        "chat", "Chat", "Everyday questions and conversation",
        _BASE + "Answer clearly and briefly. Say so when you are not sure, rather than "
        "guessing. Use Markdown only when it helps (lists, code)."),
    "code": Mode(
        "code", "Code", "Reads, edits and runs code in the folder you started in",
        _BASE + "You are a coding assistant working in the user's project. Use the tools to "
        "read, search and edit files and to run commands; look before you change anything. "
        "Give file paths relative to the working directory. "
        "Make the smallest change that solves the problem and say what you changed. "
        "Shell commands are shown to the user for approval before they run.",
        ALL_TOOLS),
    "write": Mode(
        "write", "Write", "Drafting and editing emails, essays and summaries",
        _BASE + "You help with writing. Match the tone the user asks for, keep their meaning, "
        "and prefer plain words and short sentences. When editing, return the full revised "
        "text first and then, briefly, what you changed."),
    "study": Mode(
        "study", "Study", "Answers from the files in the stick's context folder",
        _BASE + "Answer from the user's own documents in the context folder. Search and read "
        "them with the tools before answering, name the file each fact comes from, and say "
        "plainly when the documents do not cover the question.",
        READ_TOOLS),
}

DEFAULT_MODE = "chat"


def get(mode_id: str | None) -> Mode:
    return MODES.get((mode_id or "").strip().lower(), MODES[DEFAULT_MODE])


def resolve(name: str | None) -> str | None:
    """A typed mode name (or unique prefix) to its id, or None."""
    n = (name or "").strip().lower()
    if n in MODES:
        return n
    hits = [m for m in MODES if m.startswith(n)] if n else []
    return hits[0] if len(hits) == 1 else None
