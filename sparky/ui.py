"""Sparky terminal UI — a Claude-Code-style REPL in the Sparky theme.

Live streaming (you see it think + its operations), markdown output with tool
cards, a clear input area, and a bottom toolbar showing the active model that you
can cycle with Ctrl-T. Degrades to plain print/input when rich/prompt_toolkit are
unavailable so it still runs anywhere.
"""

from __future__ import annotations

from pathlib import Path

from . import __version__
from . import clipboard as clip_mod
from . import config as config_mod
from . import images as images_mod
from . import sessions as sessions_mod
from .agent import Agent
from .connectivity import Monitor
from .router import Router
from .theme import C, MASCOT, TAGLINE

try:
    from rich.console import Console
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.spinner import Spinner
    from rich.table import Table
    from rich.text import Text
    _RICH = True
except Exception:  # pragma: no cover
    _RICH = False

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style
    _PTK = True
except Exception:  # pragma: no cover
    _PTK = False

# Online models you can cycle through with Ctrl-T (offline is automatic).
ONLINE_MODELS = [("Sonnet 4.6", config_mod.DEFAULT_MODEL), ("Opus 4.8", config_mod.OPUS_MODEL)]

HELP = """\
Commands:
  /help              show this help
  /model [name]      switch online model: 'sonnet', 'opus', or a full id (or Ctrl-T)
  /img <path> ...    attach an image file to the next message (also auto-detected)
  /paste  (or /v)    paste an image from the clipboard.
                     Linux/macOS: Ctrl-V also works. Windows: type /paste
                     (Windows Terminal grabs Ctrl-V for its own paste).
  /context           show what's loaded from the drive's context/ folder
  /resume            resume your most recent conversation
  /sessions          list saved conversations
  /clear             clear the conversation history
  /yolo              toggle auto-approval of shell commands
  /quit              exit
Keys: Ctrl-T cycle model · Ctrl-V paste image · ↑/↓ history
"""


class UI:
    def __init__(self, cfg):
        self.cfg = cfg
        self.console = Console() if _RICH else None
        self.monitor = Monitor().start()
        self.router = Router(cfg, monitor=self.monitor)
        self.agent = Agent(cfg, self.router, cwd=Path.cwd())
        self.pending_images: list[dict] = []
        self.session_id = sessions_mod.new_id()
        # current online model index (match cfg.model if it's one of ours)
        self.model_idx = next((i for i, (_, m) in enumerate(ONLINE_MODELS) if m == cfg.model), 0)
        self.router.set_online_model(ONLINE_MODELS[self.model_idx][1])
        # streaming render state
        self._spin = None
        self._md = None
        self._acc = ""
        self._note = ""
        self._session = None
        if _PTK:
            cfg.data_dir.mkdir(parents=True, exist_ok=True)
            self._style = Style.from_dict({
                "bottom-toolbar": f"bg:{C['panel']} {C['muted']}",
                "arrow": f"{C['brand']} bold",
            })
            self._session = PromptSession(
                history=FileHistory(str(cfg.data_dir / "history")),
                key_bindings=self._key_bindings(),
                style=self._style,
                bottom_toolbar=self._bottom_toolbar,
            )

    # ---- model selection -----------------------------------------------
    def _is_online(self) -> bool:
        return self.monitor.online and bool(self.cfg.anthropic_api_key)

    def _model_label(self) -> str:
        if self._is_online():
            return ONLINE_MODELS[self.model_idx][0]
        return f"{self.cfg.local_model} (offline)"

    def _cycle_model(self):
        self.model_idx = (self.model_idx + 1) % len(ONLINE_MODELS)
        self.router.set_online_model(ONLINE_MODELS[self.model_idx][1])

    # ---- prompt_toolkit wiring -----------------------------------------
    def _key_bindings(self):
        kb = KeyBindings()

        @kb.add("c-t")  # cycle online model
        def _(event):
            self._cycle_model()
            event.app.invalidate()  # refresh toolbar

        @kb.add("c-v")  # paste clipboard image if present, else text
        def _(event):
            grabbed = clip_mod.grab_image()
            if grabbed:
                data, mt = grabbed
                self.pending_images.append(images_mod.encode_image_bytes(data, mt))
                event.app.current_buffer.insert_text(f"[pasted image #{len(self.pending_images)}] ")
            else:
                try:
                    event.app.current_buffer.paste_clipboard_data(event.app.clipboard.get_data())
                except Exception:
                    pass

        return kb

    def _bottom_toolbar(self):
        online = self._is_online()
        mark = "<ansigreen>● online</ansigreen>" if online else "<ansiyellow>● OFFLINE</ansiyellow>"
        imgs = f" · {len(self.pending_images)} img" if self.pending_images else ""
        return HTML(f" <b>{self._model_label()}</b>  {mark}{imgs}   "
                    f"Ctrl-T model · Ctrl-V paste · /help ")

    # ---- rendering helpers ---------------------------------------------
    def _print(self, *a, **k):
        if self.console:
            self.console.print(*a, **k)
        else:
            print(*[str(x) for x in a])

    def banner(self):
        online = self._is_online()
        if self.console:
            info = Text()
            info.append(f"Sparky ", style=f"bold {C['brand']}")
            info.append(f"v{__version__}\n", style=C["muted"])
            info.append(self._model_label(), style=C["text"])
            info.append("  ·  ", style=C["border"])
            info.append("● online" if online else "● OFFLINE", style=C["teal"] if online else C["amber"])
            info.append(f"\n{Path.cwd()}", style=C["muted"])
            grid = Table.grid(padding=(0, 2))
            grid.add_column(); grid.add_column()
            grid.add_row(Text(MASCOT, style=f"bold {C['brand']}"), info)
            self.console.print(grid)
            self.console.print(f"[{C['muted']}]/help · Ctrl-T cycle model · /paste image (or Ctrl-V) · /resume[/]\n")
        else:
            print(MASCOT)
            print(f"Sparky v{__version__} — {self._model_label()} — "
                  + ("online" if online else "OFFLINE"))
            print(f"{Path.cwd()}\n/help for commands\n")

    # ---- agent event handling (streaming) ------------------------------
    def _stop_live(self):
        if self._spin:
            self._spin.stop(); self._spin = None
        if self._md:
            self._md.stop(); self._md = None

    def on_event(self, kind: str, data: dict):
        if not self.console:
            return self._on_event_plain(kind, data)
        if kind == "thinking":
            self._acc = ""
            self._md = None
            self._spin = Live(Spinner("dots", text=Text(f" thinking · {self._model_label()}", style=C["muted"])),
                              console=self.console, refresh_per_second=12, transient=True)
            self._spin.start()
        elif kind == "assistant_delta":
            self._acc += data.get("text", "")
            if self._spin:
                self._spin.stop(); self._spin = None
            if self._md is None:
                self._md = Live(console=self.console, refresh_per_second=8, vertical_overflow="visible")
                self._md.start()
            self._md.update(Markdown(self._acc))
        elif kind == "assistant_done":
            if self._spin:
                self._spin.stop(); self._spin = None
            if self._md:
                self._md.update(Markdown(self._acc or data.get("text", "")))
                self._md.stop(); self._md = None
            if self._note:
                self.console.print(f"[{C['amber']}]{self._note}[/]")
                self._note = ""
        elif kind == "backend":
            if data.get("fallback"):
                self._note = "⚠ connection lost — switched to the local model (fallback)"
        elif kind == "tool_start":
            self._stop_live()
            self.console.print(Text.assemble(
                ("  ⚙ ", C["cyan"]), (data["name"], f"bold {C['cyan']}"),
                ("  " + _short(data.get("input"), 110), C["muted"])))
        elif kind == "tool_result":
            self.console.print(Text("    ↳ " + _short(data.get("output", ""), 200), style=C["muted"]))
        elif kind == "confirm":
            self._stop_live()
            data["holder"]["approved"] = self._confirm(data["command"])

    def _on_event_plain(self, kind, data):
        if kind == "assistant_delta":
            print(data.get("text", ""), end="", flush=True)
        elif kind == "assistant_done":
            if data.get("text"):
                print()
        elif kind == "tool_start":
            print(f"  > {data['name']} {_short(data.get('input'), 110)}")
        elif kind == "tool_result":
            print(f"    {_short(data.get('output',''), 200)}")
        elif kind == "backend" and data.get("fallback"):
            print("  (connection lost — using local model)")
        elif kind == "confirm":
            data["holder"]["approved"] = self._confirm(data["command"])

    def _confirm(self, command: str) -> bool:
        self._print(f"[{C['amber']}]Run shell command?[/] [{C['text']}]{command}[/]"
                    if self.console else f"Run shell command? {command}")
        try:
            return input("  [y/N] ").strip().lower() in ("y", "yes")
        except EOFError:
            return False

    # ---- main loop ------------------------------------------------------
    def read(self) -> str:
        if self._session:
            return self._session.prompt(HTML('<arrow>› </arrow>'))
        return input(f"\n[{self._model_label()}] › ")

    def _do_resume(self):
        d = sessions_mod.latest(self.cfg)
        if not d:
            self._print("no saved conversation to resume")
            return
        self.agent.history = d.get("history", [])
        self.session_id = d.get("id", self.session_id)
        self._print(f"resumed: {d.get('title', '(untitled)')} ({len(self.agent.history)} messages)")

    def run(self, resume: bool = False):
        self.banner()
        if resume:
            self._do_resume()
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
            if self._is_online():
                for p in images_mod.find_image_paths(line, cwd=Path.cwd()):
                    try:
                        images.append(images_mod.encode_image(p))
                    except Exception:
                        pass
            try:
                self.agent.run_turn(line, images=images, on_event=self.on_event)
                sessions_mod.save(self.cfg, self.session_id, self.agent.history)
            except Exception as e:
                self._stop_live()
                self._print(f"[{C['red']}]error: {e}[/]" if self.console else f"error: {e}")

    def _command(self, line: str) -> bool:
        parts = line.split()
        cmd = parts[0].lower()
        rest = line[len(parts[0]):].strip()
        if cmd in ("/quit", "/exit", "/q"):
            self._print("bye 👋"); return True
        if cmd in ("/help", "/h", "/?"):
            self._print(HELP)
        elif cmd == "/model":
            if not rest:
                self._print(f"current model: {self._model_label()} (Ctrl-T to cycle)")
            else:
                model = {"sonnet": config_mod.DEFAULT_MODEL, "opus": self.cfg.opus_model}.get(rest, rest)
                self.router.set_online_model(model)
                self.model_idx = next((i for i, (_, m) in enumerate(ONLINE_MODELS) if m == model), self.model_idx)
                self._print(f"online model → {model}")
        elif cmd in ("/paste", "/v"):
            grabbed = clip_mod.grab_image()
            if grabbed:
                data, mt = grabbed
                self.pending_images.append(images_mod.encode_image_bytes(data, mt))
                self._print(f"📎 pasted clipboard image ({len(data)//1024} KB, {mt}) — attached to your next message")
            elif not clip_mod.available():
                self._print("no clipboard image tool found (install xclip / wl-clipboard on Linux)")
            else:
                self._print("no image in the clipboard — copy a screenshot (or an image file), then /paste")
        elif cmd == "/resume":
            self._do_resume()
        elif cmd == "/sessions":
            items = sessions_mod.list_sessions(self.cfg)[:10]
            self._print("\n".join(f"  {d.get('id','?')}  {d.get('title','(untitled)')}" for d in items)
                        if items else "no saved conversations yet")
        elif cmd == "/context":
            from .context import load_context
            ctx = load_context(self.cfg.context_dir)
            self._print(ctx[:2000] if ctx else "context/ folder is empty")
        elif cmd == "/clear":
            self.agent.history.clear(); self.session_id = sessions_mod.new_id()
            self._print("history cleared")
        elif cmd == "/yolo":
            self.cfg.yolo = not self.cfg.yolo
            self._print(f"YOLO (auto-approve shell) is now {'ON' if self.cfg.yolo else 'OFF'}")
        else:
            self._print(f"unknown command: {cmd} (try /help)")
        return False


def _short(value, limit: int = 100) -> str:
    s = str(value).replace("\n", " ")
    return s if len(s) <= limit else s[:limit] + "…"


def run(cfg, resume: bool = False):
    UI(cfg).run(resume=resume)
