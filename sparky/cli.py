"""Command line: `python -m sparky [command] [options]`, normally run
through the launcher (sparky.cmd), which sets up the stick's runtime first.

    (none)      chat in the terminal
    web         chat in the browser
    ask         one answer, printed; text piped in is added to the question
    serve       just the model server, for other apps
    models      list, add, remove, recommend, catalog
    doctor      check this computer, the runtime and the models
    setup       the setup wizard (make a stick, add OSes or models)
    runtime     fetch the runtime for this or other computers (used by launchers)
"""

from __future__ import annotations

import argparse
import sys

from . import __version__, catalog, hardware, modes
from . import config as config_mod


def _force_utf8() -> None:
    # Windows consoles default to a legacy code page that cannot print the
    # box drawing and arrows the UI uses; fall back to replacement, not a crash.
    for stream in (sys.stdout, sys.stderr):
        try:
            # line buffering keeps progress and error lines in order in a pipe or log
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            pass


def build_parser() -> argparse.ArgumentParser:
    # SUPPRESS: a subcommand repeating these options must not reset a value
    # given before it (`sparky --mode code web`) to its default
    common = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    common.add_argument("--model", "-m", help="model to use (any installed name)")
    common.add_argument("--mode", choices=list(modes.MODES), help="chat, code, write or study")
    common.add_argument("--yolo", action="store_true", help="run shell commands without asking")
    common.add_argument("--think", action="store_true", help="show the reasoning of thinking models")

    p = argparse.ArgumentParser(prog="sparky", parents=[common],
                                description="Open-weight AI from a USB stick.")
    p.add_argument("--version", action="version", version=f"Sparky {__version__}")
    p.add_argument("--resume", action="store_true", help="continue the last conversation")
    p.add_argument("--self-test", "--selftest", dest="self_test", action="store_true",
                   help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="command")

    sub.add_parser("chat", parents=[common], help="chat in the terminal (the default)") \
        .add_argument("--resume", action="store_true")

    w = sub.add_parser("web", parents=[common], help="chat in the browser")
    w.add_argument("--port", type=int, default=0, help="port (default: a free one)")
    w.add_argument("--no-browser", action="store_true", help="print the address instead of opening it")

    a = sub.add_parser("ask", parents=[common], help="one answer to stdout")
    a.add_argument("prompt", nargs="*", help="the question; text piped in is appended")

    sub.add_parser("serve", help="run only the model server (OpenAI-compatible /v1)")

    m = sub.add_parser("models", help="list, add or remove models")
    m.add_argument("action", nargs="?", default="list",
                   choices=["list", "add", "remove", "recommend", "catalog", "use"])
    m.add_argument("names", nargs="*")
    m.add_argument("--for", dest="purpose", choices=list(catalog.PURPOSES), default="everyday")
    m.add_argument("--ram", type=float, default=0, help="GB of memory to plan for (default: this computer)")

    sub.add_parser("doctor", help="check this computer, the runtime and the models")

    s = sub.add_parser("setup", help="set up a stick (or a folder)")
    s.add_argument("--target", help="the stick or folder to set up")
    s.add_argument("--for", dest="purposes", help="comma-separated purposes: " + ",".join(catalog.PURPOSES))
    s.add_argument("--models", help="comma-separated model tags (instead of recommendations)")
    s.add_argument("--ram", type=float, default=0, help="GB of memory of the computers it will run on")
    s.add_argument("--os", dest="targets", default="",
                   help="all, this, or a comma list such as windows-x86_64,macos-aarch64")
    s.add_argument("--no-models", action="store_true", help="skip downloading models")
    s.add_argument("--gpu", action="store_true", help="keep Ollama's GPU libraries (much bigger)")
    s.add_argument("--yes", "-y", action="store_true", help="do not ask; accept the recommendations")
    s.add_argument("--force", action="store_true", help="continue even on a FAT32 drive")

    r = sub.add_parser("runtime", help=argparse.SUPPRESS)
    r.add_argument("--os", dest="targets", default="this")
    r.add_argument("--gpu", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    cfg = config_mod.load()
    if getattr(args, "yolo", False):
        cfg.yolo = True
    if getattr(args, "think", False):
        cfg.think = True
    if getattr(args, "mode", None):
        cfg.mode = args.mode
    if getattr(args, "model", None):
        cfg.model = args.model

    cmd = args.command or ("doctor" if args.self_test else "chat")
    try:
        if cmd == "chat":
            from .ui import run
            run(cfg, resume=bool(getattr(args, "resume", False)))
            return 0
        if cmd == "web":
            from .web.server import serve_web
            return serve_web(cfg, port=args.port, open_browser=not args.no_browser)
        if cmd == "ask":
            from .oneshot import ask
            return ask(cfg, " ".join(args.prompt))
        if cmd == "serve":
            from .oneshot import serve
            return serve(cfg)
        if cmd == "models":
            from .manage import models_command
            return models_command(cfg, args)
        if cmd == "doctor":
            from .manage import doctor
            return doctor(cfg)
        if cmd == "setup":
            from .wizard import run_wizard
            return run_wizard(cfg, args)
        if cmd == "runtime":
            from . import runtime
            targets = _targets(args.targets)
            runtime.ensure(cfg.root, targets, progress=_line_progress, gpu=args.gpu)
            print()
            return 0
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    return 0


def _targets(spec: str) -> list[str]:
    from . import runtime
    spec = (spec or "").strip().lower()
    if spec in ("", "this"):
        return [hardware.target()]
    if spec == "all":
        return list(runtime.DEFAULT_TARGETS)
    if spec == "every":
        return list(runtime.TARGETS)
    out = []
    for t in spec.split(","):
        t = t.strip()
        if t == "macos":
            out += ["macos-aarch64", "macos-x86_64"]
        elif t in ("windows", "linux"):
            out.append(f"{t}-x86_64")
        elif t:
            out.append(t)
    return out


def _line_progress(text: str) -> None:
    """One updating status line in a terminal, plain lines otherwise."""
    if sys.stdout.isatty():
        sys.stdout.write("\r\033[K" + text[:110])
        sys.stdout.flush()
    else:
        print(text)
