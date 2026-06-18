"""Entrypoint: `python -m sparky [--self-test] [--yolo] [--resume]`.

Runs the --self-test diagnostic, then launches the TUI. Sparky is fully local —
there is no API key to capture and no network needed.
"""

from __future__ import annotations

import sys

from . import config as config_mod
from . import __version__
from .providers.local import LocalProvider


def self_test(cfg) -> int:
    ok = True

    def line(label, good, detail=""):
        nonlocal ok
        mark = "✓" if good else "✗"
        if not good:
            ok = False
        print(f"  {mark} {label}{(' — ' + detail) if detail else ''}")

    print(f"Sparky {__version__} self-test (fully local)")
    print(f"Python {sys.version.split()[0]} at {sys.executable}")
    line("rich installed", _has("rich"))
    line("prompt_toolkit installed", _has("prompt_toolkit"))
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
            for tier, model in cfg.tiers:
                has = any(model.split(":")[0] in n for n in names)
                line(f"{tier} model {model} pulled", has, ", ".join(names) or "none")
        except Exception as e:
            line("list local models", False, str(e))
    # Offline inference spawns a native binary; FAT mounts (showexec) make it
    # non-executable. Flag that so "ollama reachable" isn't mistaken for ready.
    import glob
    import os as _os
    runners = glob.glob(str(cfg.runtime_dir / "ollama" / "pkg" / "*" / "lib" / "ollama" / "llama-server"))
    runners += glob.glob(str(cfg.runtime_dir / "ollama" / "pkg" / "*" / "lib" / "ollama" / "llama-server.exe"))
    if runners and not any(_os.access(r, _os.X_OK) for r in runners):
        print("  ! the local runtime isn't executable here (FAT stick). "
              "Run `sudo tools/format_exfat.sh` to enable it on Linux.")

    print("\nReady." if ok else "\nSome checks failed (see above).")
    return 0 if ok else 1


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


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
    from .ui import run
    run(cfg, resume=("--resume" in argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
