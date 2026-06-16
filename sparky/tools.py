"""Agent tools — filesystem + shell, the surface that makes Sparky a coding
copilot rather than a chatbot. Specs are in Anthropic tool schema shape.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

MAX_READ_BYTES = 100_000
MAX_OUTPUT = 20_000

TOOL_SPECS: list[dict] = [
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file and return its contents.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path, relative to the working dir or absolute."}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a file with the given content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace the first exact occurrence of old_str with new_str in a file. old_str must appear exactly once.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_str": {"type": "string"},
                "new_str": {"type": "string"},
            },
            "required": ["path", "old_str", "new_str"],
        },
    },
    {
        "name": "list_dir",
        "description": "List files and directories at a path (defaults to the working directory).",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Directory path. Defaults to '.'"}},
            "required": [],
        },
    },
    {
        "name": "search",
        "description": "Recursively search text files for a regex pattern and return matching lines with file:line.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "description": "Directory to search. Defaults to '.'"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "run_shell",
        "description": "Run a shell command in the working directory and return stdout+stderr. Asks the user for approval unless YOLO mode is on.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
]


def _resolve(cwd: Path, path: str) -> Path:
    p = Path(path).expanduser()
    return p if p.is_absolute() else (cwd / p)


def _truncate(s: str, limit: int = MAX_OUTPUT) -> str:
    return s if len(s) <= limit else s[:limit] + f"\n…[truncated, {len(s)} bytes total]"


def run_tool(name: str, args: dict, *, cwd: Path, confirm=None) -> str:
    """Dispatch a tool call. `confirm(command) -> bool` gates run_shell."""
    try:
        if name == "read_file":
            p = _resolve(cwd, args["path"])
            data = p.read_bytes()[:MAX_READ_BYTES]
            return _truncate(data.decode("utf-8", "replace"))

        if name == "write_file":
            p = _resolve(cwd, args["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args["content"], encoding="utf-8")
            return f"Wrote {len(args['content'])} bytes to {p}"

        if name == "edit_file":
            p = _resolve(cwd, args["path"])
            text = p.read_text(encoding="utf-8")
            old = args["old_str"]
            count = text.count(old)
            if count == 0:
                return f"Error: old_str not found in {p}"
            if count > 1:
                return f"Error: old_str appears {count} times in {p}; make it unique."
            p.write_text(text.replace(old, args["new_str"], 1), encoding="utf-8")
            return f"Edited {p}"

        if name == "list_dir":
            p = _resolve(cwd, args.get("path", "."))
            if not p.exists():
                return f"Error: {p} does not exist"
            entries = sorted(os.listdir(p))
            lines = [f"{'d' if (p / e).is_dir() else '-'} {e}" for e in entries]
            return _truncate("\n".join(lines) or "(empty)")

        if name == "search":
            base = _resolve(cwd, args.get("path", "."))
            try:
                rx = re.compile(args["pattern"])
            except re.error as e:
                return f"Error: bad regex: {e}"
            hits: list[str] = []
            for root, dirs, files in os.walk(base):
                dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "__pycache__", "runtime"}]
                for fn in files:
                    fp = Path(root) / fn
                    try:
                        for i, line in enumerate(fp.read_text(encoding="utf-8", errors="strict").splitlines(), 1):
                            if rx.search(line):
                                hits.append(f"{fp}:{i}: {line.strip()}")
                                if len(hits) >= 200:
                                    return _truncate("\n".join(hits) + "\n…[200-match cap]")
                    except (UnicodeDecodeError, OSError):
                        continue
            return _truncate("\n".join(hits)) if hits else "No matches."

        if name == "run_shell":
            cmd = args["command"]
            if confirm is not None and not confirm(cmd):
                return "Command was not approved by the user."
            proc = subprocess.run(
                cmd, shell=True, cwd=str(cwd), capture_output=True, text=True, timeout=120,
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            return _truncate(f"(exit {proc.returncode})\n{out}".rstrip())

        return f"Error: unknown tool '{name}'"
    except FileNotFoundError as e:
        return f"Error: file not found: {e}"
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 120s"
    except Exception as e:  # surface any tool error back to the model
        return f"Error running {name}: {e}"
