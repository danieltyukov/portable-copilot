"""Entrypoint: `python -m sparky [--self-test] [--yolo]`.

Handles first-run API-key capture and the --self-test diagnostic, then launches
the TUI.
"""

from __future__ import annotations

import sys

from . import config as config_mod
from . import __version__
from .connectivity import _reachable
from .providers.local import LocalProvider


def self_test(cfg) -> int:
    ok = True

    def line(label, good, detail=""):
        nonlocal ok
        mark = "✓" if good else "✗"
        if not good:
            ok = False
        print(f"  {mark} {label}{(' — ' + detail) if detail else ''}")

    print(f"Sparky {__version__} self-test")
    print(f"Python {sys.version.split()[0]} at {sys.executable}")
    line("rich installed", _has("rich"))
    line("prompt_toolkit installed", _has("prompt_toolkit"))
    line("Anthropic API key present", bool(cfg.anthropic_api_key))
    online = _reachable()
    line("internet (api.anthropic.com reachable)", online, "online" if online else "offline — local mode")
    local = LocalProvider(cfg)
    up = local.reachable()
    line("Ollama reachable", up, cfg.ollama_host)
    if up:
        import json
        import urllib.request
        try:
            with urllib.request.urlopen(f"{local.host}/api/tags", timeout=3) as r:
                tags = json.loads(r.read())
            names = [m.get("name", "") for m in tags.get("models", [])]
            has_model = any(cfg.local_model.split(":")[0] in n for n in names)
            line(f"local model {cfg.local_model} pulled", has_model, ", ".join(names) or "none")
        except Exception as e:
            line("list local models", False, str(e))
    # Offline inference spawns a native binary; FAT mounts (showexec) make it
    # non-executable. Flag that so "ollama reachable" isn't mistaken for offline-ready.
    import glob
    import os as _os
    runners = glob.glob(str(cfg.runtime_dir / "ollama" / "pkg" / "*" / "lib" / "ollama" / "llama-server"))
    runners += glob.glob(str(cfg.runtime_dir / "ollama" / "pkg" / "*" / "lib" / "ollama" / "llama-server.exe"))
    if runners and not any(_os.access(r, _os.X_OK) for r in runners):
        print("  ! offline inference: the local runtime isn't executable here "
              "(FAT stick). Run `sudo tools/format_exfat.sh` to enable offline on Linux.")

    print("\nReady." if ok else "\nSome checks failed (see above).")
    return 0 if ok else 1


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


def first_run_setup(cfg):
    """If no key and we're online, offer to paste an Anthropic API key."""
    if cfg.anthropic_api_key or not _reachable():
        return cfg
    print("No Anthropic API key found. Paste one to use Claude online")
    print("(or just press Enter to run offline with the local model).")
    try:
        key = input("ANTHROPIC_API_KEY: ").strip()
    except (EOFError, KeyboardInterrupt):
        return cfg
    if key:
        config_mod.write_env(cfg, {"ANTHROPIC_API_KEY": key})
        print("Saved to data/sparky.env (chmod 600).")
        return config_mod.load(root=cfg.root)
    return cfg


def _force_utf8():
    # Windows consoles default to cp1252/cp437, which can't encode ✓ ● ⚙ etc.
    # and would crash on print(). Force UTF-8 (with replace as a safety net).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv=None) -> int:
    _force_utf8()
    argv = list(sys.argv[1:] if argv is None else argv)
    cfg = config_mod.load()
    if "--yolo" in argv:
        cfg.yolo = True
    if "--self-test" in argv or "--selftest" in argv:
        return self_test(cfg)
    cfg = first_run_setup(cfg)
    from .ui import run
    run(cfg, resume=("--resume" in argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
