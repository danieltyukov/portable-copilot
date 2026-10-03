"""The terminal chat: replies stream in as Markdown, tools show as they run,
and a bottom toolbar shows the model and mode.

Ctrl-T moves to the next installed model and Ctrl-C stops a reply. It falls
back to plain print and input when rich or prompt_toolkit are missing, so it
runs from any terminal.
"""

from __future__ import annotations

from pathlib import Path

from . import __version__, catalog, engine
from . import clipboard as clip_mod
from . import images as images_mod
from . import modes as modes_mod
from . import sessions as sessions_mod
from .context import list_files, load_context
from .manage import pull
from .providers.base import Cancelled, ModelNotFound, ProviderError
from .theme import ACCENT, C, TAGLINE, mascot_rows

try:
    from rich import box
    from rich.console import Console
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.panel import Panel
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

HELP = """\
Commands
  /model [name]    switch model (any installed name, or part of one); no name lists them
  /models          the models on this stick, and what else would fit
  /pull <name>     download a model while online (a tag, hf.co/..., or a purpose like code)
  /mode [name]     chat, code, write or study
  /think           show or hide the reasoning of models that think first
  /img <path>      attach an image to your next message (or just mention its path)
  /paste           attach the image on the clipboard
  /context         what is in the stick's context folder
  /resume          continue your last conversation;  /sessions lists them
  /clear           start a new conversation
  /yolo            run shell commands without asking (code mode)
  /quit            exit (or Ctrl-D)
Keys
  Ctrl-T next model   Ctrl-C stop the reply   Up/Down history
"""


class UI:
    def __init__(self, cfg):
        self.cfg = cfg
        self.console = Console(highlight=False) if _RICH else None
        self.agent = engine.build(cfg)
        self.router = self.agent.router
        self.pending_images: list[dict] = []
        self.session_id = sessions_mod.new_id()
        self._spin = None
        self._think = None
        self._md = None
        self._acc = ""
        self._thought = ""
        self._session = None
        self._last_interrupt = False
        if _PTK and self.console is not None:
            cfg.data_dir.mkdir(parents=True, exist_ok=True)
            self._session = PromptSession(
                history=FileHistory(str(cfg.data_dir / "history")),
                key_bindings=self._key_bindings(),
                style=Style.from_dict({
                    "bottom-toolbar": f"noreverse bg:{C['panel']} {C['muted']}",
                    "bottom-toolbar.model": f"bold {ACCENT}",
                    "arrow": f"{ACCENT} bold",
                }),
                bottom_toolbar=self._bottom_toolbar,
            )

    # ---- labels ---------------------------------------------------------------------
    def _model_label(self) -> str:
        return self.router.model or "no model"

    def _mode_label(self) -> str:
        return self.agent.mode_obj.label

    def _print(self, *a, **k):
        if self.console:
            self.console.print(*a, **k)
        else:
            print(*[str(x) for x in a])

    def _say(self, text: str, colour: str = "muted"):
        if self.console:
            self.console.print(Text(text, style=C.get(colour, colour)))
        else:
            print(text)

    # ---- prompt_toolkit --------------------------------------------------------------
    def _key_bindings(self):
        kb = KeyBindings()

        @kb.add("c-t")
        def _(event):
            self.router.cycle()
            event.app.invalidate()

        @kb.add("c-v")
        def _(event):
            grabbed = clip_mod.grab_image()
            if grabbed:
                data, mt = grabbed
                self.pending_images.append(images_mod.encode_image_bytes(data, mt))
                event.app.current_buffer.insert_text(f"[image {len(self.pending_images)}] ")
            else:
                try:
                    event.app.current_buffer.paste_clipboard_data(event.app.clipboard.get_data())
                except Exception:
                    pass

        return kb

    def _bottom_toolbar(self):
        imgs = f"  ·  {len(self.pending_images)} image(s) attached" if self.pending_images else ""
        think = "  ·  thinking shown" if self.router.think else ""
        yolo = "  ·  <ansired>yolo</ansired>" if self.cfg.yolo else ""
        return HTML(f" <model>{_esc(self._model_label())}</model>  ·  {self._mode_label()}{think}{yolo}"
                    f"{imgs}   <ansigreen>●</ansigreen> on this computer"
                    f"   Ctrl-T model  /help ")

    # ---- banner ------------------------------------------------------------------------
    def banner(self):
        if not self.console:
            print(f"Sparky {__version__}, {TAGLINE}")
            print(f"{self._model_label()} · {self._mode_label()} · {self.agent.cwd}")
            print("/help for commands\n")
            return
        art = Text()
        for i, row in enumerate(mascot_rows()):
            for ch, style in row:
                art.append(ch, style=style)
            if i < len(mascot_rows()) - 1:
                art.append("\n")
        info = Text()
        info.append(TAGLINE + "\n\n", style=C["muted"])
        info.append("● ", style=C["green"])
        info.append("on this computer   ", style=C["muted"])
        info.append(self._model_label(), style=f"bold {C['text']}")
        info.append(f"  ·  {self._mode_label()} mode\n", style=C["muted"])
        info.append(str(self.agent.cwd) + "\n\n", style=C["dim"])
        info.append("/help  ·  Ctrl-T next model  ·  /mode  ·  Ctrl-C stops a reply", style=C["dim"])
        grid = Table.grid(padding=(0, 3))
        grid.add_column(no_wrap=True)
        grid.add_column()
        grid.add_row(art, info)
        title = Text.assemble(("Sparky", f"bold {ACCENT}"), (f" {__version__}", C["dim"]))
        self.console.print(Panel(grid, title=title, title_align="left", box=box.ROUNDED,
                                 border_style=ACCENT, padding=(1, 2)))
        if not self.router.model:
            self._say(engine.no_models_message(self.cfg), "amber")
        self.console.print()

    # ---- streaming events ------------------------------------------------------------
    def _stop_live(self):
        self._stop_spin_only()
        self._stop_think()
        if self._md:
            self._md.stop()
            self._md = None

    def _spinner(self, text: str):
        if self._spin:
            self._spin.update(Spinner("dots", text=Text(" " + text, style=C["muted"]), style=ACCENT))
            return
        self._spin = Live(Spinner("dots", text=Text(" " + text, style=C["muted"]), style=ACCENT),
                          console=self.console, refresh_per_second=12, transient=True)
        self._spin.start()

    def on_event(self, kind: str, data: dict):
        if not self.console:
            return self._on_event_plain(kind, data)
        if kind == "thinking":
            self._acc = ""
            self._thought = ""
            self._spinner(f"{self._model_label()} is working")
        elif kind == "think_delta":
            self._thought += data.get("text", "")
            if self.router.think:
                self._stop_spin_only()
                if self._think is None:
                    self._think = Live(console=self.console, refresh_per_second=8,
                                       vertical_overflow="visible")
                    self._think.start()
                self._think.update(Text(self._thought.strip(), style=f"italic {C['dim']}"))
            else:
                words = len(self._thought.split())
                self._spinner(f"{self._model_label()} is thinking ({words} words so far)")
        elif kind == "assistant_delta":
            self._acc += data.get("text", "")
            if not self._acc.strip():
                return
            self._stop_spin_only()
            self._stop_think()
            if self._md is None:
                self._md = Live(console=self.console, refresh_per_second=8, vertical_overflow="visible")
                self._md.start()
            self._md.update(Markdown(self._acc))
        elif kind == "assistant_done":
            self._stop_spin_only()
            self._stop_think()
            if self._md:
                if self._acc:
                    self._md.update(Markdown(self._acc))
                self._md.stop()
                self._md = None
        elif kind == "stats":
            self._print(Text(f"  {data.get('model')}  ·  {data.get('tokens')} tokens  ·  "
                             f"{data.get('tps')} tokens/s", style=C["dim"]))
        elif kind == "notice":
            self._stop_live()
            self._say("  " + data.get("text", ""), "amber")
        elif kind == "tool_start":
            self._stop_live()
            name = data["name"]
            room = self.console.width - len(name) - 6
            self.console.print(Text.assemble(
                ("  ● ", C["cyan"]), (name, f"bold {C['cyan']}"),
                ("  " + _short(_tool_summary(name, data.get("input")), room), C["muted"])), no_wrap=True)
        elif kind == "tool_result":
            self.console.print(Text("    └ " + _short(data.get("output", ""), self.console.width - 8),
                                    style=C["dim"]), no_wrap=True)
        elif kind == "confirm":
            self._stop_live()
            data["holder"]["approved"] = self._confirm(data["command"])

    def _stop_spin_only(self):
        if self._spin:
            self._spin.stop()
            self._spin = None

    def _stop_think(self):
        if self._think:
            self._think.stop()
            self._think = None

    def _on_event_plain(self, kind, data):
        if kind == "assistant_delta":
            print(data.get("text", ""), end="", flush=True)
        elif kind == "assistant_done":
            if data.get("text"):
                print()
        elif kind == "tool_start":
            print(f"  > {data['name']} {_short(_tool_summary(data['name'], data.get('input')), 100)}")
        elif kind == "tool_result":
            print(f"    {_short(data.get('output', ''), 200)}")
        elif kind == "notice":
            print(f"  ({data.get('text')})")
        elif kind == "stats":
            print(f"  [{data.get('model')}, {data.get('tps')} tokens/s]")
        elif kind == "confirm":
            data["holder"]["approved"] = self._confirm(data["command"])

    def _confirm(self, what: str) -> bool:
        if self.console:
            self.console.print(Text.assemble(("  Allow? ", f"bold {C['amber']}"), (what, C["text"])))
        else:
            print(f"  Allow? {what}")
        try:
            return input("  [y/N] ").strip().lower() in ("y", "yes")
        except EOFError:
            return False

    # ---- main loop ------------------------------------------------------------------
    def read(self) -> str:
        if self._session:
            return self._session.prompt(HTML("<arrow>› </arrow>"))
        return input(f"\n[{self._model_label()}] > ")

    def run(self, resume: bool = False):
        self.banner()
        if resume:
            self._do_resume()
        while True:
            try:
                line = self.read()
                self._last_interrupt = False
            except EOFError:
                self._say("bye")
                return
            except KeyboardInterrupt:
                if self._last_interrupt:
                    self._say("bye")
                    return
                self._last_interrupt = True
                self._say("(press Ctrl-C again, Ctrl-D, or type /quit to exit)")
                continue
            line = line.strip()
            if not line:
                continue
            if line.startswith("/"):
                if self._command(line):
                    return
                continue
            self.turn(line)

    def turn(self, line: str):
        images = self.pending_images
        self.pending_images = []
        for p in images_mod.find_image_paths(line, cwd=Path.cwd()):
            try:
                images.append(images_mod.encode_image(p))
            except Exception:
                pass
        if images and not self.router.supports("vision"):
            self._say(f"  {self._model_label()} cannot see images; it will only get your text. "
                      "Try a model that reads images (/models).", "amber")
        if not self.router.model:
            self._say(engine.no_models_message(self.cfg), "amber")
            return
        try:
            self.agent.run_turn(line, images=images, on_event=self.on_event)
            sessions_mod.save(self.cfg, self.session_id, self.agent.history)
            self._print()
        except Cancelled:
            self._stop_live()
            self._say("  stopped", "amber")
        except ModelNotFound:
            self._stop_live()
            names = ", ".join(self.router.manager.names()) or "none"
            self._say(f"  {self._model_label()} is not on this stick. Installed: {names}.\n"
                      f"  Pick one with /model, or download it with /pull {self._model_label()}", "red")
        except ProviderError as e:
            self._stop_live()
            self._say(f"  {e}", "red")
        except Exception as e:  # keep the session alive whatever happens
            self._stop_live()
            self._say(f"  error: {e}", "red")

    def _do_resume(self):
        d = sessions_mod.latest(self.cfg)
        if not d:
            self._say("no saved conversation to resume")
            return
        self.agent.history = d.get("history", [])
        self.session_id = d.get("id", self.session_id)
        self._say(f"resumed: {d.get('title', '(untitled)')} ({len(self.agent.history)} messages)")

    # ---- slash commands -----------------------------------------------------------------
    def _command(self, line: str) -> bool:
        parts = line.split()
        cmd = parts[0].lower()
        rest = line[len(parts[0]):].strip()
        if cmd in ("/quit", "/exit", "/q"):
            self._say("bye")
            return True
        if cmd in ("/help", "/h", "/?"):
            self._print(Text(HELP, style=C["text"]) if self.console else HELP)
        elif cmd == "/model":
            if not rest:
                self._list_models()
            elif self.router.set_model(rest):
                self._say(f"model: {self._model_label()}", "text")
            else:
                self._say(f"no installed model matches '{rest}'. Installed: "
                          f"{', '.join(self.router.manager.names()) or 'none'}", "amber")
        elif cmd == "/models":
            self._list_models(suggest=True)
        elif cmd == "/pull":
            self._pull(rest)
        elif cmd == "/mode":
            if not rest:
                for m in modes_mod.MODES.values():
                    mark = "*" if m.id == self.agent.mode else " "
                    self._say(f" {mark} {m.id:<6} {m.blurb}", "text")
            else:
                hit = modes_mod.resolve(rest)
                if hit:
                    self.agent.mode = hit
                    self._say(f"mode: {self._mode_label()}", "text")
                else:
                    self._say("modes: chat, code, write, study", "amber")
        elif cmd == "/think":
            self.router.think = not self.router.think
            if self.router.supports("thinking"):
                self._say("reasoning will be shown" if self.router.think else "reasoning hidden (quicker)", "text")
            else:
                self._say(f"{self._model_label()} does not think before answering; the setting applies "
                          "to models that do", "text")
        elif cmd in ("/img", "/image"):
            self._attach(rest)
        elif cmd in ("/paste", "/v"):
            grabbed = clip_mod.grab_image()
            if grabbed:
                data, mt = grabbed
                self.pending_images.append(images_mod.encode_image_bytes(data, mt))
                self._say(f"attached the clipboard image ({len(data) // 1024} KB) to your next message", "text")
            elif not clip_mod.available():
                self._say("no clipboard tool found (on Linux install xclip or wl-clipboard)", "amber")
            else:
                self._say("no image on the clipboard; copy a screenshot or an image file, then /paste", "amber")
        elif cmd == "/resume":
            self._do_resume()
        elif cmd == "/sessions":
            items = sessions_mod.list_sessions(self.cfg)[:10]
            self._say("\n".join(f"  {d.get('id', '?')}  {d.get('title', '(untitled)')}" for d in items)
                      if items else "no saved conversations yet", "text")
        elif cmd == "/context":
            files = list_files(self.cfg.context_dir)
            if not files:
                self._say(f"the context folder is empty: {self.cfg.context_dir}", "text")
            else:
                self._say(f"{len(files)} file(s) in {self.cfg.context_dir}:", "text")
                ctx = load_context(self.cfg.context_dir)
                self._say(ctx[:1500] + ("\n..." if len(ctx) > 1500 else ""), "muted")
        elif cmd == "/clear":
            self.agent.history.clear()
            self.session_id = sessions_mod.new_id()
            self._say("new conversation", "text")
        elif cmd == "/yolo":
            self.cfg.yolo = not self.cfg.yolo
            self._say("shell commands now run without asking" if self.cfg.yolo
                      else "shell commands will ask first again", "amber" if self.cfg.yolo else "text")
        else:
            self._say(f"unknown command {cmd} (try /help)", "amber")
        return False

    def _attach(self, rest: str):
        path = rest.split()[0] if rest else ""
        try:
            self.pending_images.append(images_mod.encode_image(Path(path).expanduser()))
            self._say(f"attached {path} to your next message", "text")
        except Exception as e:
            self._say(f"could not attach '{path}': {e}", "amber")

    def _list_models(self, suggest: bool = False):
        installed = self.router.manager.installed(refresh=True)
        if not installed:
            self._say(engine.no_models_message(self.cfg), "amber")
        width = self.console.width if self.console else 100
        for m in installed:
            mark = "*" if m.name == self.router.model else " "
            e = catalog.find(m.name)
            self._say(_short(f" {mark} {m.name:<24} {m.size_gb:>5.1f} GB  {e.note if e else ''}", width - 1),
                      "text")
        if suggest:
            from . import hardware
            ram = hardware.total_ram_gb()
            free = hardware.free_gb(self.cfg.root)
            have = set(self.router.manager.names())
            more = [e for e in catalog.recommend("everyday", ram, free, n=6) if e.tag not in have][:3]
            if more:
                self._say(f"\nAlso fits this computer ({ram:.0f} GB) and the stick ({free:.0f} GB free):", "muted")
                for e in more:
                    self._say(f"   {e.tag:<24} {e.size_gb:>5.1f} GB  {e.note}", "muted")
                self._say("Download one with /pull <name> (needs the internet).", "muted")

    def _pull(self, rest: str):
        name = rest.strip()
        if not name:
            self._say("usage: /pull <name>   e.g. /pull qwen3.5:4b, /pull code, /pull hf.co/user/repo", "amber")
            return
        if name in catalog.PURPOSES:
            from . import hardware
            picks = catalog.recommend(name, hardware.total_ram_gb(), hardware.free_gb(self.cfg.root))
            if not picks:
                self._say(f"nothing in the catalog for {name} fits here", "amber")
                return
            name = picks[0].tag
        try:
            ok = pull(self.router.manager.client, name, self.cfg)
        except KeyboardInterrupt:
            self._say("\n  download stopped; run /pull again to resume it", "amber")
            return
        if ok:
            self.router.manager.installed(refresh=True)
            self.router.set_model(name)
            self._say(f"model: {self._model_label()}", "text")


def _tool_summary(name: str, value) -> str:
    """The part of a tool call worth showing: the path, the pattern, the
    command. Not the full text of an edit, which would flood the screen."""
    if not isinstance(value, dict):
        return str(value)
    if name == "run_shell":
        return str(value.get("command", ""))
    if name == "search":
        where = value.get("path")
        return f"{value.get('pattern', '')}" + (f"  in {where}" if where else "")
    if name == "write_file":
        lines = str(value.get("content", "")).count("\n") + 1
        return f"{value.get('path', '')}  ({lines} lines)"
    if "path" in value:
        return str(value["path"])
    return "  ".join(f"{k}={v}" for k, v in value.items())


def _short(value, limit: int = 100) -> str:
    s = str(value).replace("\n", " ")
    return s if len(s) <= limit else s[:limit] + "..."


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def run(cfg, resume: bool = False):
    UI(cfg).run(resume=resume)
