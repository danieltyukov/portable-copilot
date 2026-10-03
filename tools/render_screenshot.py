"""Render the README screenshots of the terminal app from the real UI.

The UI class draws everything (banner, streamed Markdown, tool cards, the
approval prompt, the speed line) into a recording console with a scripted
conversation, which is exported as SVG and rasterised, so the pictures can
never drift from what the app draws. No model server is needed.

    python3 tools/render_screenshot.py        # needs rich; inkscape for the PNGs
"""

from __future__ import annotations

import builtins
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PureWindowsPath

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rich.console import Console  # noqa: E402
from rich.terminal_theme import TerminalTheme  # noqa: E402
from rich.text import Text  # noqa: E402

from sparky import config, ui as ui_mod  # noqa: E402
from sparky.agent import Agent  # noqa: E402
from sparky.models import Installed  # noqa: E402
from sparky.providers.base import Reply, ToolCall  # noqa: E402
from sparky.theme import ACCENT, C  # noqa: E402

# The same palette as meeting-copilot's screenshots, so the family matches.
THEME = TerminalTheme(
    (13, 17, 23), (230, 237, 243),
    [(13, 17, 23), (248, 113, 113), (52, 211, 153), (251, 191, 36),
     (56, 189, 248), (232, 121, 249), (56, 189, 248), (230, 237, 243)],
    [(125, 133, 144), (248, 113, 113), (52, 211, 153), (251, 191, 36),
     (56, 189, 248), (232, 121, 249), (56, 189, 248), (255, 255, 255)],
)


class StillLive:
    """Live, but for a recording: draws its last frame once when stopped,
    instead of redrawing in place (and draws nothing if transient)."""

    def __init__(self, renderable=None, console=None, transient=False, **_):
        self.renderable, self.console, self.transient = renderable, console, transient

    def start(self):
        pass

    def update(self, renderable):
        self.renderable = renderable

    def stop(self):
        if not self.transient and self.renderable is not None:
            self.console.print(self.renderable)


class Manager:
    def __init__(self):
        self.models = [Installed("qwen3.5:4b", 3.4), Installed("qwen3-coder:30b", 19.0)]

    def installed(self, refresh=False):
        return self.models

    def names(self):
        return [m.name for m in self.models]

    def capabilities(self, name):
        return {"completion", "tools", "vision", "thinking"} if "3.5" in name else {"completion", "tools"}

    def resolve(self, q):
        return next((n for n in self.names() if n.startswith(q)), None)


class Router:
    def __init__(self, replies):
        self.manager = Manager()
        self.model = "qwen3.5:4b"
        self.think = False
        self.replies = replies
        self.last_fallback = False
        self.fallback_from = ""

    def supports(self, cap, model=None):
        return cap in self.manager.capabilities(model or self.model)

    def set_model(self, name):
        self.model = self.manager.resolve(name) or self.model
        return self.model

    def cycle(self):
        names = self.manager.names()
        self.model = names[(names.index(self.model) + 1) % len(names)]
        return self.model

    def chat_stream(self, messages, tools=None, system=None, on_text=None, on_think=None, cancel=None):
        reply = self.replies.pop(0)
        for word in reply.text.split(" "):
            on_text(word + " ")
        return reply, self.model

    def abort(self):
        pass


def say(console, text):
    console.print(Text.assemble(("› ", f"bold {ACCENT}"), (text, C["text"])))


def toolbar(console, model, mode):
    console.print()
    line = Text(" ", style=f"on {C['panel']}")
    line.append(model, style=f"bold {ACCENT} on {C['panel']}")
    line.append(f"  ·  {mode}   ", style=f"{C['muted']} on {C['panel']}")
    line.append("●", style=f"{C['green']} on {C['panel']}")
    line.append(" on this computer   Ctrl-T model  /help ", style=f"{C['muted']} on {C['panel']}")
    line.pad_right(console.width - line.cell_len)
    line.stylize(f"on {C['panel']}")
    console.print(line)


def render(name: str, script) -> Path:
    ui_mod._PTK = False
    ui_mod.Live = StillLive
    with tempfile.TemporaryDirectory() as tmp:
        cfg = config.load(root=Path(tmp))
        cfg.ollama_host = "http://127.0.0.1:9"
        console = Console(record=True, width=100, force_terminal=True, color_system="truecolor",
                          file=open("/dev/null", "w") if sys.platform != "win32" else None)
        tui = ui_mod.UI.__new__(ui_mod.UI)
        tui.cfg = cfg
        tui.console = console
        tui.pending_images = []
        tui.session_id = "shot"
        tui._spin = tui._think = tui._md = None
        tui._acc = tui._thought = ""
        tui._session = None
        tui._last_interrupt = False
        replies = []
        tui.router = Router(replies)
        tui.agent = Agent(cfg, tui.router, cwd=Path(tmp), ctx_tokens=8192)
        script(tui, replies)
    svg = ROOT / "docs" / f"{name}.svg"
    console.save_svg(str(svg), title="sparky", theme=THEME)
    png = svg.with_suffix(".png")
    if shutil.which("inkscape"):
        subprocess.run(["inkscape", str(svg), "--export-type=png", f"--export-filename={png}", "-w", "1640"],
                       check=True, capture_output=True)
    return png


def chat(tui, replies):
    tui.agent.cwd = PureWindowsPath("E:\\")     # started from a stick on Windows
    tui.banner()
    q = "What does open-weight mean? Two sentences."
    say(tui.console, q)
    replies.append(Reply(
        text="It means the trained model itself, the file of weights, is published for anyone to "
             "download and run on their own computer. You can use it offline and nobody sees your "
             "prompts, though the training data and code are often not released.",
        tool_calls=[], content_blocks=[], stats={"tokens": 52, "tps": 17.4}))
    tui.agent.run_turn(q, on_event=tui.on_event)
    say(tui.console, "/model")
    tui._list_models()
    tui.console.print()
    toolbar(tui.console, "qwen3.5:4b", "Chat")


def code(tui, replies):
    tui.agent.mode = "code"
    tui.agent.cwd = Path("/home/ann/projects/photo-tools")
    tui.router.model = "qwen3-coder:30b"
    q = "Add a --dry-run flag to rename.py that prints the new names instead of renaming."
    say(tui.console, q)
    old = "    os.rename(src, dst)"
    new = "    if args.dry_run:\n        print(f\"{src} -> {dst}\")\n    else:\n        os.rename(src, dst)"
    replies += [
        Reply(text="", tool_calls=[ToolCall("1", "read_file", {"path": "rename.py"})],
              content_blocks=[{"type": "tool_use", "id": "1", "name": "read_file", "input": {"path": "rename.py"}}]),
        Reply(text="", tool_calls=[ToolCall("2", "edit_file", {"path": "rename.py", "old_str": old, "new_str": new})],
              content_blocks=[{"type": "tool_use", "id": "2", "name": "edit_file",
                               "input": {"path": "rename.py", "old_str": old, "new_str": new}}]),
        Reply(text="", tool_calls=[ToolCall("3", "run_shell", {"command": "python rename.py photos/ --dry-run"})],
              content_blocks=[{"type": "tool_use", "id": "3", "name": "run_shell",
                               "input": {"command": "python rename.py photos/ --dry-run"}}]),
        Reply(text="Added `--dry-run`. With it, `rename.py` prints each `old -> new` pair and leaves the "
                   "files alone; without it, nothing changes. I ran it on `photos/` and the three names it "
                   "printed look right.", tool_calls=[], content_blocks=[],
              stats={"tokens": 61, "tps": 12.8}),
    ]
    import sparky.tools as tools_mod
    outputs = iter([
        "import argparse\nimport os\n...\n    os.rename(src, dst)\n",
        "Edited rename.py",
        "(exit 0)\nphotos/IMG_0412.jpg -> photos/2026-09-14_0412.jpg\n"
        "photos/IMG_0413.jpg -> photos/2026-09-14_0413.jpg\nphotos/IMG_0420.jpg -> photos/2026-09-15_0420.jpg",
    ])

    def fake_run(name, args, *, cwd, confirm=None):
        if name == "run_shell" and confirm and not confirm(f"run: {args['command']}"):
            return "The user did not approve this command."
        return next(outputs)

    real_run, real_input = tools_mod.run_tool, builtins.input
    tools_mod.run_tool = fake_run
    builtins.input = lambda prompt="": (tui.console.print(Text(prompt + "y", style=C["text"])), "y")[1]
    try:
        tui.agent.run_turn(q, on_event=tui.on_event)
    finally:
        tools_mod.run_tool, builtins.input = real_run, real_input
    toolbar(tui.console, "qwen3-coder:30b", "Code")


if __name__ == "__main__":
    for name, script in (("screenshot", chat), ("screenshot-code", code)):
        print("wrote", render(name, script))
