"""Sparky terminal UI — a Claude-Code-style REPL in the Sparky theme.

Uses `rich` for rendering and `prompt_toolkit` for the input line when available,
and degrades to plain print/input otherwise so the tool still runs anywhere.
"""

from __future__ import annotations

from pathlib import Path

from . import config as config_mod
from . import images as images_mod
from .agent import Agent
from .connectivity import Monitor
from .router import Router
from .theme import C, MASCOT, TAGLINE

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.text import Text
    _RICH = True
except Exception:  # pragma: no cover - exercised only without the dep
    _RICH = False

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    _PTK = True
except Exception:  # pragma: no cover
    _PTK = False


HELP = """\
Commands:
  /help              show this help
  /model [name]      switch online model: 'sonnet', 'opus', or a full id
  /img <path> ...    attach an image to the next message (also auto-detected in prompts)
  /context           show what's loaded from the drive's context/ folder
  /clear             clear the conversation history
  /yolo              toggle auto-approval of shell commands
  /quit              exit
"""


class UI:
    def __init__(self, cfg):
        self.cfg = cfg
        self.console = Console() if _RICH else None
        self.monitor = Monitor().start()
        self.router = Router(cfg, monitor=self.monitor)
        self.agent = Agent(cfg, self.router, cwd=Path.cwd())
        self.pending_images: list[dict] = []
        self._session = None
        if _PTK:
            cfg.data_dir.mkdir(parents=True, exist_ok=True)
            self._session = PromptSession(history=FileHistory(str(cfg.data_dir / "history")))

    # ---- rendering helpers ---------------------------------------------
    def _print(self, *a, **k):
        if self.console:
            self.console.print(*a, **k)
        else:
            print(*[str(x) for x in a])

    def _status_line(self) -> str:
        online = self.monitor.online and bool(self.cfg.anthropic_api_key)
        if online:
            return f"● online · {self.router.claude.model}"
        return f"● OFFLINE · {self.router.local.model}"

    def banner(self):
        if self.console:
            mascot = Text(MASCOT, style=f"bold {C['brand']}")
            title = Text("\n Sparky\n", style=f"bold {C['brand']}")
            title.append(f" {TAGLINE}\n", style=C["muted"])
            title.append(f" {self._status_line()}", style=C["teal"] if self.monitor.online else C["amber"])
            self.console.print(Panel.fit(
                Text.assemble(mascot, "   ", title),
                border_style=C["border"], padding=(0, 2),
            ))
            self.console.print(f"[{C['muted']}]/help for commands · working dir: {Path.cwd()}[/]")
        else:
            print(MASCOT)
            print("Sparky —", TAGLINE)
            print(self._status_line())
            print("/help for commands · working dir:", Path.cwd())

    # ---- agent event handling ------------------------------------------
    def on_event(self, kind: str, data: dict):
        if kind == "assistant":
            text = data.get("text", "")
            if not text:
                return
            if self.console:
                self.console.print(Markdown(text))
            else:
                print(text)
        elif kind == "tool_start":
            self._print(f"[{C['cyan']}]⚙ {data['name']}[/] [{C['muted']}]{_short(data.get('input'))}[/]"
                        if self.console else f"⚙ {data['name']} {_short(data.get('input'))}")
        elif kind == "tool_result":
            out = data.get("output", "")
            self._print(f"[{C['muted']}]  ↳ {_short(out, 160)}[/]" if self.console else f"  ↳ {_short(out, 160)}")
        elif kind == "backend":
            if data.get("fallback"):
                self._print(f"[{C['amber']}]⚠ lost connection — switched to local model (fallback)[/]"
                            if self.console else "⚠ lost connection — switched to local model (fallback)")
        elif kind == "confirm":
            data["holder"]["approved"] = self._confirm(data["command"])

    def _confirm(self, command: str) -> bool:
        self._print(f"[{C['amber']}]Run shell command?[/] [{C['text']}]{command}[/]"
                    if self.console else f"Run shell command? {command}")
        try:
            ans = input("  [y/N] ").strip().lower()
        except EOFError:
            return False
        return ans in ("y", "yes")

    # ---- main loop ------------------------------------------------------
    def read(self) -> str:
        marker = self._status_line()
        prompt = f"\n{marker}\nsparky> "
        if self._session:
            return self._session.prompt(prompt)
        return input(prompt)

    def run(self):
        self.banner()
        while True:
            try:
                line = self.read()
            except (EOFError, KeyboardInterrupt):
                self._print("\nbye 👋")
                return
            line = line.strip()
            if not line:
                continue
            if line.startswith("/"):
                if self._command(line):
                    return
                continue
            images = self.pending_images
            self.pending_images = []
            # auto-detect image paths in the prompt when online
            if self.monitor.online and self.cfg.anthropic_api_key:
                for p in images_mod.find_image_paths(line, cwd=Path.cwd()):
                    try:
                        images.append(images_mod.encode_image(p))
                    except Exception:
                        pass
            try:
                self.agent.run_turn(line, images=images, on_event=self.on_event)
            except Exception as e:
                self._print(f"[{C['red']}]error: {e}[/]" if self.console else f"error: {e}")

    def _command(self, line: str) -> bool:
        """Handle a slash command. Returns True if the app should exit."""
        parts = line.split()
        cmd = parts[0].lower()
        rest = line[len(parts[0]):].strip()
        if cmd in ("/quit", "/exit", "/q"):
            self._print("bye 👋")
            return True
        if cmd in ("/help", "/h", "/?"):
            self._print(HELP)
        elif cmd == "/model":
            if not rest:
                self._print(f"current online model: {self.router.claude.model}")
            else:
                model = {"sonnet": config_mod.DEFAULT_MODEL, "opus": self.cfg.opus_model}.get(rest, rest)
                self.router.set_online_model(model)
                self._print(f"online model → {model}")
        elif cmd == "/img":
            if not rest:
                self._print("usage: /img <path> [your message]")
            else:
                ip = images_mod.find_image_paths(rest, cwd=Path.cwd())
                if not ip:
                    self._print(f"[{C['red']}]no readable image found in: {rest}[/]" if self.console else f"no image found: {rest}")
                else:
                    for p in ip:
                        self.pending_images.append(images_mod.encode_image(p))
                    self._print(f"attached {len(ip)} image(s) to your next message")
        elif cmd == "/context":
            from .context import load_context
            ctx = load_context(self.cfg.context_dir)
            self._print(ctx[:2000] if ctx else "context/ folder is empty")
        elif cmd == "/clear":
            self.agent.history.clear()
            self._print("history cleared")
        elif cmd == "/yolo":
            self.cfg.yolo = not self.cfg.yolo
            self._print(f"YOLO (auto-approve shell) is now {'ON' if self.cfg.yolo else 'OFF'}")
        else:
            self._print(f"unknown command: {cmd} (try /help)")
        return False


def _short(value, limit: int = 100) -> str:
    s = str(value)
    s = s.replace("\n", " ")
    return s if len(s) <= limit else s[:limit] + "…"


def run(cfg):
    UI(cfg).run()
