"""The setup wizard: `./setup.sh`, `setup.bat` or `sparky.cmd setup`.

Asks where to install, what it is for and what computers it will meet, then
copies Sparky, fetches a runtime for each operating system and downloads
models that fit. Every question has a default, and every answer can be given
as a flag instead, so the same code serves a first-timer and a script.

Running it again on a stick that already has Sparky updates the app and adds
whatever is missing; conversations, settings and models are kept.
"""

from __future__ import annotations

import os
import shutil
import socket
import sys
from pathlib import Path

from . import catalog, hardware, runtime
from . import config as config_mod
from .manage import pull

APP_FILES = ["sparky.cmd", "start.sh", "START.bat", "start.command", "setup.sh", "setup.bat",
             "README.md", "LICENSE"]
APP_TOOLS = ["fetch_python.sh", "fetch_python.ps1", "start_server.ps1", "format_exfat.sh"]
CONTEXT_README = """\
Put files here that you want Sparky to know about: notes, documents, code,
exported chats. The text of these files is given to the model with every
conversation, as much as fits. In Study mode Sparky can also open and search
them, so large folders work too. Subfolders are fine. PDFs and images are
listed by name but not read as text; save the parts that matter as .txt or .md.
"""

MODE_FOR = {"code": "code", "study": "study", "write": "write"}
RAM_CHOICES = [("Older or small laptops", 8), ("Most laptops", 16), ("Powerful computers", 32)]


class Wizard:
    def __init__(self, cfg, args):
        self.cfg = cfg
        self.args = args
        self.yes = bool(getattr(args, "yes", False))
        self.src = config_mod.find_root()

    # ---- talking -----------------------------------------------------------------
    def say(self, text: str = "") -> None:
        print(text)

    def head(self, text: str) -> None:
        print(f"\n\033[1m{text}\033[0m" if sys.stdout.isatty() else f"\n{text}")

    def menu_head(self, text: str) -> None:
        if not self.yes:
            self.head(text)

    def menu(self, text: str = "") -> None:
        """A line of a question's choices: not shown when --yes answers it."""
        if not self.yes:
            print(text)

    def ask(self, prompt: str, default: str = "") -> str:
        if self.yes:
            return default
        try:
            got = input(f"{prompt} [{default}]: " if default else f"{prompt}: ").strip()
        except EOFError:
            got = ""
        return got or default

    def confirm(self, prompt: str) -> bool:
        return self.ask(prompt + " (y/n)", "y").lower().startswith("y")

    # ---- steps ---------------------------------------------------------------------
    def run(self) -> int:
        self.say("Sparky setup\n" + "-" * 30)
        self.say("This puts Sparky and open-weight AI models on a USB stick (or a folder), so\n"
                 "you can use them on any Windows, macOS or Linux computer without installing\n"
                 "anything. It needs the internet now; the stick does not, afterwards.")
        target = self.choose_target()
        if target is None:
            return 1
        if not self.check_drive(target):
            return 1
        targets = self.choose_targets(target)
        runtime_gb = self.runtime_gb(target, targets)
        purposes = self.choose_purposes()
        ram = self.choose_ram()
        space = hardware.free_gb(target) - runtime_gb - 1.0
        chosen = [] if getattr(self.args, "no_models", False) else self.choose_models(purposes, ram, space)
        if chosen is None:
            return 1

        self.head("Ready to install")
        self.say(f"  Where:     {target}")
        self.say(f"  Runs on:   {self.describe_targets(targets)}")
        self.say(f"  Models:    {', '.join(chosen) or 'none for now'}")
        size = sum((catalog.find(t).size_gb if catalog.find(t) else 0) for t in chosen)
        self.say(f"  Download:  about {size + self.download_gb(target, targets):.1f} GB")
        if not self.confirm("Start?"):
            self.say("Nothing was changed.")
            return 1
        return self.install(target, targets, purposes, chosen)

    def choose_target(self) -> Path | None:
        given = getattr(self.args, "target", None)
        if given:
            p = Path(given).expanduser().resolve()
            p.mkdir(parents=True, exist_ok=True)
            return p
        drives = hardware.list_drives()
        self.menu_head("Where to install")
        options: list[Path] = []
        for d in drives:
            options.append(d.path)
            tag = "  (removable)" if d.removable else ""
            self.menu(f"  {len(options)}) {d.describe()}{tag}")
        self.menu("  f) a folder on this computer (type its path)")
        if not drives:
            self.menu("  No USB drives found. Plug one in and run setup again, or choose a folder.")
        pick = self.ask("Choose", "1" if drives else "f")
        if pick.isdigit() and 1 <= int(pick) <= len(options):
            return options[int(pick) - 1]
        if pick.lower() == "f":
            pick = self.ask("Folder path", str(Path.home() / "Sparky"))
        if pick and not pick.isdigit():
            p = Path(pick).expanduser().resolve()
            p.mkdir(parents=True, exist_ok=True)
            return p
        self.menu("That is not one of the choices.")
        return None

    def check_drive(self, target: Path) -> bool:
        kind = hardware.fstype(target)
        problem = hardware.fs_problem(kind)
        if problem:
            self.say("\n" + problem + "\n\n" + hardware.exfat_steps())
            if not getattr(self.args, "force", False):
                self.say("\nRun setup again once it is exFAT (or add --force to continue anyway).")
                return False
        warn = hardware.fs_warning(kind)
        if warn:
            self.say("\nNote: " + warn)
        if (target / "sparky").is_dir() and target != self.src:
            self.say("\nSparky is already here. It will be updated; your settings, conversations,"
                     "\ncontext folder and models are kept.")
        return True

    def choose_purposes(self) -> list[str]:
        given = getattr(self.args, "purposes", None)
        ids = list(catalog.PURPOSES)
        if given:
            return [p.strip() for p in given.split(",") if p.strip() in catalog.PURPOSES] or ["everyday"]
        self.menu_head("What will you use it for?")
        for i, (pid, (label, blurb)) in enumerate(catalog.PURPOSES.items(), 1):
            self.menu(f"  {i}) {label:<20} {blurb}")
        got = self.ask("Choose one or more, e.g. 1,3", "1")
        out = []
        for part in got.replace(" ", ",").split(","):
            if part.isdigit() and 1 <= int(part) <= len(ids):
                out.append(ids[int(part) - 1])
            elif part in catalog.PURPOSES:
                out.append(part)
        return list(dict.fromkeys(out)) or ["everyday"]

    def choose_ram(self) -> float:
        given = float(getattr(self.args, "ram", 0) or 0)
        if given:
            return given
        here = hardware.total_ram_gb()
        self.menu_head("The computers you will plug it into")
        self.menu("Models need memory to run. Plan for the smallest computer you expect to use;")
        self.menu("on bigger ones you can add larger models later.")
        for i, (label, gb) in enumerate(RAM_CHOICES, 1):
            self.menu(f"  {i}) {label} ({gb} GB of memory)")
        if here:
            self.menu(f"  {len(RAM_CHOICES) + 1}) Only this computer ({here:.0f} GB)")
        default = "2" if not here or here >= 16 else "1"
        got = self.ask("Choose", default)
        if got.isdigit() and 1 <= int(got) <= len(RAM_CHOICES):
            return float(RAM_CHOICES[int(got) - 1][1])
        if here and got == str(len(RAM_CHOICES) + 1):
            return here
        try:
            return float(got)
        except ValueError:
            return 16.0

    def choose_models(self, purposes: list[str], ram: float, space: float) -> list[str] | None:
        given = getattr(self.args, "models", None)
        if given:
            return [t.strip() for t in given.split(",") if t.strip()]
        plan = catalog.plan(purposes, ram, space)
        self.head("Models")
        if space < 1:
            self.say("There is no room left for models on this drive. Free some space or use a bigger stick.")
            return []
        if not plan:
            self.say("Nothing in the catalog fits that memory and space. You can add a model by name later.")
            return []
        self.say(f"Recommended for {ram:.0f} GB computers, with {space:.0f} GB of room on the drive:\n")
        for i, e in enumerate(plan, 1):
            self.say(f"  {i}) {e.tag:<22} {e.size_gb:>5.1f} GB  {e.speed:<6}  {e.note}")
        self.say("\nPress Enter to take these, type numbers to keep only some (e.g. 1),")
        self.say("type model names to choose your own, or 'list' to see the whole catalog.")
        while True:
            got = self.ask("Models", "")
            if got.lower() == "list":
                from .manage import print_entries
                print_entries([e for e in sorted(catalog.ENTRIES, key=lambda e: e.size_gb)
                               if catalog.fits(e, ram, space)], ram)
                continue
            if not got:
                return [e.tag for e in plan]
            parts = [p for p in got.replace(",", " ").split() if p]
            if all(p.isdigit() and 1 <= int(p) <= len(plan) for p in parts):
                return [plan[int(p) - 1].tag for p in parts]
            return parts

    def choose_targets(self, target: Path) -> list[str]:
        given = getattr(self.args, "targets", "")
        if given:
            from .cli import _targets
            return _targets(given)
        here = hardware.target()
        default = list(runtime.DEFAULT_TARGETS)
        if here not in default and here in runtime.TARGETS:
            default.append(here)
        if self.yes:
            return default
        self.menu_head("Operating systems")
        self.menu(f"The stick will run on: {self.describe_targets(default)}.")
        got = self.ask("Press Enter for all of these, or type 'this' for only this computer's system", "")
        if got.strip().lower() == "this":
            return [here]
        if got.strip():
            from .cli import _targets
            return _targets(got)
        return default

    # ---- estimates ---------------------------------------------------------------
    @staticmethod
    def describe_targets(targets: list[str]) -> str:
        names = []
        if any(t.startswith("windows") for t in targets):
            names.append("Windows")
        macs = [t for t in targets if t.startswith("macos")]
        if len(macs) == 2:
            names.append("macOS (Apple Silicon and Intel)")
        elif macs:
            names.append("macOS (" + ("Apple Silicon" if "aarch64" in macs[0] else "Intel") + ")")
        if any(t.startswith("linux") for t in targets):
            names.append("Linux")
        return ", ".join(names) or "nothing"

    @staticmethod
    def runtime_gb(target: Path, targets: list[str]) -> float:
        have = set(runtime.installed_targets(target))
        fams = {t.split("-")[0] for t in targets if t not in have}
        return sum(runtime.SIZE_MB[f] for f in fams) / 1000 + 0.05

    @staticmethod
    def download_gb(target: Path, targets: list[str]) -> float:
        have = set(runtime.installed_targets(target))
        return sum(runtime.DOWNLOAD_MB[t] for t in set(targets) - have) / 1000

    # ---- doing it ------------------------------------------------------------------
    def install(self, target: Path, targets: list[str], purposes: list[str], models: list[str]) -> int:
        from .cli import _line_progress

        if target != self.src:
            self.head("Copying Sparky")
            copy_app(self.src, target)
        (target / "context").mkdir(exist_ok=True)
        seed = target / "context" / "README.txt"
        if not seed.exists():
            seed.write_text(CONTEXT_README, encoding="utf-8")

        cfg = config_mod.load(target)
        updates = {"SPARKY_MODE": MODE_FOR.get(purposes[0], "chat")}
        if models:
            updates["SPARKY_MODEL"] = models[0]
        config_mod.write_env(cfg, updates, remove=("SPARKY_FAST_MODEL", "SPARKY_MAX_MODEL", "SPARKY_TIER"))

        self.head("Fetching the runtime")
        try:
            runtime.ensure(target, targets, progress=_line_progress, gpu=getattr(self.args, "gpu", False))
        except Exception as e:
            print()
            self.say(f"Could not fetch the runtime: {e}\nCheck the internet connection and run setup again;"
                     " anything already downloaded is kept.")
            return 1
        print()

        failed = []
        if models:
            self.head("Downloading models")
            host = f"http://127.0.0.1:{free_port()}"
            try:
                with runtime.server(target, host, progress=_line_progress, reuse=False) as client:
                    print()
                    for tag in models:
                        if not pull(client, tag, cfg):
                            failed.append(tag)
            except RuntimeError as e:
                self.say(f"Could not start the model server: {e}")
                failed = models

        self.head("Done" if not failed else "Done, with problems")
        if failed:
            self.say(f"These models were not added: {', '.join(failed)}. Add them later with\n"
                     f"  sparky.cmd models add <name>")
        self.say(f"Sparky is in {target}. On any computer, open that folder and:")
        self.say("  Windows:  double-click sparky.cmd")
        self.say("  macOS:    double-click start.command (the first time: right-click, Open)")
        self.say("  Linux:    run ./sparky.cmd in a terminal")
        self.say("For the browser version, run:  sparky.cmd web")
        cache = runtime.cache_dir()
        size = sum(f.stat().st_size for f in cache.glob("*") if f.is_file()) / 1e9
        if size > 0.1:
            self.say(f"\nDownloads are cached in {cache} ({size:.1f} GB) to make the next stick\n"
                     "quicker. Delete that folder whenever you like.")
        return 0 if not failed else 1


def copy_app(src: Path, dst: Path) -> None:
    """Copy the app (not the runtime, data or models) from src to dst."""
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")
    shutil.copytree(src / "sparky", dst / "sparky", ignore=ignore, dirs_exist_ok=True)
    (dst / "tools").mkdir(exist_ok=True)
    for name in APP_TOOLS:
        if (src / "tools" / name).exists():
            shutil.copyfile(src / "tools" / name, dst / "tools" / name)
    for name in APP_FILES:
        if (src / name).exists():
            shutil.copyfile(src / name, dst / name)
    for name in ("sparky.cmd", "start.sh", "start.command", "setup.sh",
                 "tools/fetch_python.sh", "tools/format_exfat.sh"):
        try:
            os.chmod(dst / name, 0o755)
        except OSError:
            pass   # exFAT and FAT have no permission bits; their mounts decide


def free_port() -> int:
    """A port nobody is using, so setup's own model server never talks to
    (or pulls into) another stick's server that is already running."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_wizard(cfg, args) -> int:
    try:
        return Wizard(cfg, args).run()
    except KeyboardInterrupt:
        print("\nSetup stopped. Run it again to carry on; finished downloads are kept.")
        return 130
