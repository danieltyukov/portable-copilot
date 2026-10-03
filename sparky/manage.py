"""`sparky.cmd models ...` and `sparky.cmd doctor`."""

from __future__ import annotations

import sys

from . import __version__, catalog, hardware, runtime
from . import config as config_mod
from .models import ModelManager
from .ollama import OllamaClient, OllamaError, PullProgress


def _ram(args=None) -> float:
    return float(getattr(args, "ram", 0) or 0) or hardware.total_ram_gb()


def _fit_note(size_gb: float, ram_gb: float) -> str:
    need = size_gb + (1.5 if size_gb < 10 else 2.5)
    if not ram_gb:
        return ""
    return "fits" if need <= catalog.usable_ram(ram_gb) else f"needs about {need:.0f} GB of memory"


def print_entries(entries: list[catalog.Entry], ram_gb: float) -> None:
    for e in entries:
        flags = ", ".join(x for x, on in (("images", e.vision), ("tools", e.tools),
                                         ("thinks", e.thinking)) if on)
        print(f"  {e.tag:<24} {e.size_gb:>5.1f} GB  {e.speed:<6}  {e.note}")
        extra = f"{e.name}, {e.maker}, {e.licence}" + (f"; {flags}" if flags else "")
        fit = _fit_note(e.size_gb, ram_gb)
        print(f"  {'':<24} {'':>8}  {'':<6}  {extra}" + (f" ({fit})" if fit and fit != "fits" else ""))


def models_command(cfg, args) -> int:
    action = args.action
    ram = _ram(args)
    if action == "catalog":
        print("Models Sparky knows well (any Ollama tag or hf.co/<user>/<repo> works too).")
        print("Speed is for a typical laptop without a GPU; Apple Silicon is quicker.\n")
        print_entries(sorted(catalog.ENTRIES, key=lambda e: e.size_gb), ram)
        return 0
    if action == "recommend":
        free = hardware.free_gb(cfg.root)
        label, blurb = catalog.PURPOSES[args.purpose]
        picks = catalog.recommend(args.purpose, ram, free)
        print(f"For {label.lower()} ({blurb.lower()}),")
        print(f"on a computer with {ram:.0f} GB of memory and {free:.0f} GB free on the stick:\n")
        if not picks:
            print("  Nothing in the catalog fits. Try a smaller purpose or free some space.")
            return 1
        print_entries(picks, ram)
        print(f"\nAdd the first with:  sparky.cmd models add {picks[0].tag}")
        return 0

    try:
        with runtime.server(cfg.root, cfg.ollama_host, progress=lambda t: None) as client:
            return _with_server(cfg, client, args, ram)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _with_server(cfg, client: OllamaClient, args, ram: float) -> int:
    manager = ModelManager(cfg, client)
    action = args.action
    if action == "list":
        installed = manager.installed()
        if not installed:
            print("No models on this stick yet. See what fits:  sparky.cmd models recommend")
            return 0
        default = manager.default()
        print(f"Models on this stick ({hardware.free_gb(cfg.root):.0f} GB free):\n")
        for m in installed:
            mark = "*" if m.name == default else " "
            entry = catalog.find(m.name)
            note = entry.note if entry else (f"{m.family} {m.params}".strip())
            fit = _fit_note(m.size_gb, ram)
            print(f" {mark} {m.name:<26} {m.size_gb:>5.1f} GB  {note}"
                  + (f" ({fit} on this computer)" if fit and fit != "fits" else ""))
        print("\n* opens by default. Change it with:  sparky.cmd models use <name>")
        return 0

    if not args.names:
        print(f"Usage: sparky.cmd models {action} <name> [<name> ...]", file=sys.stderr)
        return 2

    if action == "use":
        hit = manager.resolve(args.names[0])
        if not hit:
            print(f"{args.names[0]} is not on this stick. Installed: {', '.join(manager.names())}",
                  file=sys.stderr)
            return 1
        config_mod.write_env(cfg, {"SPARKY_MODEL": hit})
        print(f"Sparky will open with {hit}.")
        return 0

    if action == "remove":
        status = 0
        for name in args.names:
            hit = manager.resolve(name) or name
            try:
                client.delete(hit)
                print(f"Removed {hit}.")
            except OllamaError as e:
                print(f"Could not remove {name}: {e}", file=sys.stderr)
                status = 1
        return status

    # add
    status = 0
    for name in args.names:
        tag = name
        if name in catalog.PURPOSES:
            picks = catalog.recommend(name, ram, hardware.free_gb(cfg.root))
            if not picks:
                print(f"No catalog model for {name} fits here.", file=sys.stderr)
                status = 1
                continue
            tag = picks[0].tag
            print(f"Best fit for {name} on this computer: {tag}")
        if not pull(client, tag, cfg):
            status = 1
    return status


def pull(client: OllamaClient, tag: str, cfg=None) -> bool:
    """Download one model with a progress line. Returns success."""
    entry = catalog.find(tag)
    if cfg is not None and entry:
        free = hardware.free_gb(cfg.root)
        if entry.size_gb > free:
            print(f"{tag} needs {entry.size_gb:.1f} GB but the stick has {free:.1f} GB free.",
                  file=sys.stderr)
            return False
    progress = PullProgress()
    tty = sys.stdout.isatty()
    last = ""
    print(f"Adding {tag}")
    try:
        def show(ev):
            nonlocal last
            line = progress.update(ev)
            if not line or line == last:
                return
            if tty:
                sys.stdout.write("\r\033[K  " + line)
                sys.stdout.flush()
            elif line[:14] != last[:14]:
                # in a log or pipe, one line per status and per ten percent
                print("  " + line)
            last = line
        client.pull(tag, show)
    except OllamaError as e:
        if tty:
            print()
        msg = str(e)
        if "newer version" in msg:
            msg = "this model needs a newer model server than the stick has; run setup again to update it"
        elif "file does not exist" in msg or "not found" in msg:
            msg = "no such model; check the name at https://ollama.com/library"
        print(f"  Could not add {tag}: {msg}", file=sys.stderr)
        return False
    if tty:
        print()
    print(f"  {tag} is ready.")
    return True


def doctor(cfg) -> int:
    ok = True

    def line(state: str, text: str) -> None:
        nonlocal ok
        if state == "FAIL":
            ok = False
        print(f"[{state}] {text}")

    ram = hardware.total_ram_gb()
    print(f"Sparky {__version__} doctor\n" + "-" * 30)
    print(f"Computer: {hardware.target()}, {hardware.cpu_count()} CPU threads, "
          f"{ram:.1f} GB memory ({hardware.available_ram_gb():.1f} GB free), {hardware.accelerator()}")
    print(f"Python:   {sys.version.split()[0]} at {sys.executable}")
    print(f"Stick:    {cfg.root}")

    kind = hardware.fstype(cfg.root)
    problem = hardware.fs_problem(kind)
    if problem:
        line("FAIL", problem)
    elif hardware.fs_warning(kind):
        line("WARN", hardware.fs_warning(kind))
    else:
        line("PASS", f"filesystem {kind or 'unknown'}, {hardware.free_gb(cfg.root):.1f} GB free")

    for mod in ("rich", "prompt_toolkit"):
        try:
            __import__(mod)
            line("PASS", f"{mod} available")
        except ImportError:
            line("WARN", f"{mod} missing; the terminal UI falls back to plain text")

    targets = runtime.installed_targets(cfg.root)
    if targets:
        line("PASS", "runtimes on the stick: " + ", ".join(targets))
    else:
        line("WARN", "no bundled runtimes in runtime/ (fine when running from a checkout)")

    client = OllamaClient(cfg.ollama_host)
    if not client.reachable():
        line("FAIL", f"model server not reachable at {cfg.ollama_host} (start Sparky through sparky.cmd)")
        print("\nSome checks failed." if not ok else "")
        return 1
    try:
        line("PASS", f"model server {client.version()} at {cfg.ollama_host}")
    except OllamaError:
        line("PASS", f"model server at {cfg.ollama_host}")

    manager = ModelManager(cfg, client)
    installed = manager.installed()
    if not installed:
        line("FAIL", "no models on the stick; add one with: sparky.cmd models add qwen3.5:4b")
    for m in installed:
        need = m.size_gb + (1.5 if m.size_gb < 10 else 2.5)
        if ram and need > catalog.usable_ram(ram):
            line("WARN", f"{m.name} ({m.size_gb:.1f} GB) may not fit this computer's memory; "
                         "a smaller model will answer instead")
        else:
            line("PASS", f"{m.name} ({m.size_gb:.1f} GB)")
    if installed:
        print(f"\nOpens with: {manager.default()}   context window: "
              f"{config_mod.context_window(cfg, ram)} tokens")
    print("\nReady." if ok else "\nSome checks failed (see above).")
    return 0 if ok else 1
