"""Puts the runtime for each operating system onto the stick, and starts the
bundled model server when a command needs it.

Per OS the stick holds a portable Python (python-build-standalone) and an
Ollama build; the pure-Python libraries in runtime/pylib and the model
weights in runtime/ollama/models are shared by every OS.

Everything is fetched from pinned GitHub releases over HTTPS and checked
against the SHA-256 list each release publishes. The Ollama builds for Linux
and Windows are mostly GPU libraries (over 1.3 GB each) that a portable,
CPU-only stick never uses, so they are left out: Windows downloads only the
files it needs from the zip, using HTTP range requests (those files are
checked with the zip's own CRC-32); the Linux archive cannot be read that way,
so it is downloaded once, verified, and cached.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from . import __version__, hardware

PBS_TAG = "20261003"
PBS_PY = "3.12.15"
OLLAMA_TAG = "v0.35.1"
PY_DEPS = ["rich", "prompt_toolkit"]
UA = f"sparky-setup/{__version__}"

PBS_URL = f"https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_TAG}"
OLLAMA_URL = f"https://github.com/ollama/ollama/releases/download/{OLLAMA_TAG}"

TARGETS: dict[str, tuple[str, str]] = {
    # target          python triple                 Ollama asset
    "windows-x86_64": ("x86_64-pc-windows-msvc", "ollama-windows-amd64.zip"),
    "windows-aarch64": ("aarch64-pc-windows-msvc", "ollama-windows-arm64.zip"),
    "macos-aarch64": ("aarch64-apple-darwin", "ollama-darwin.tgz"),
    "macos-x86_64": ("x86_64-apple-darwin", "ollama-darwin.tgz"),
    "linux-x86_64": ("x86_64-unknown-linux-gnu", "ollama-linux-amd64.tar.zst"),
    "linux-aarch64": ("aarch64-unknown-linux-gnu", "ollama-linux-arm64.tar.zst"),
}
# What a stick gets unless told otherwise: every computer most people meet.
DEFAULT_TARGETS = ["windows-x86_64", "macos-aarch64", "macos-x86_64", "linux-x86_64"]

# Rough space on the stick per target, for the wizard's estimate.
SIZE_MB = {"windows": 160, "macos": 300, "linux": 190}
DOWNLOAD_MB = {"windows-x86_64": 50, "windows-aarch64": 230, "macos-aarch64": 185,
               "macos-x86_64": 185, "linux-x86_64": 1480, "linux-aarch64": 1590}

GPU_DIRS = ("cuda", "rocm", "vulkan", "mlx", "jetpack")

Progress = Callable[[str], None]


def _say(progress: Progress | None, text: str) -> None:
    if progress:
        progress(text)


# ---- where things go ----------------------------------------------------------------

def python_dir(root: Path, target: str) -> Path:
    return root / "runtime" / "python" / target


def ollama_dir(root: Path, target: str) -> Path:
    # one universal macOS build serves both Intel and Apple Silicon
    return root / "runtime" / "ollama" / "pkg" / ("macos" if target.startswith("macos") else target)


def python_exe(root: Path, target: str) -> Path | None:
    d = python_dir(root, target)
    for p in (d / "python.exe", d / "bin" / "python3.12", d / "bin" / "python3"):
        if p.exists():
            return p
    return None


def ollama_exe(root: Path, target: str) -> Path | None:
    d = ollama_dir(root, target)
    for p in (d / "ollama.exe", d / "bin" / "ollama", d / "ollama"):
        if p.exists():
            return p
    return None


def _stamp(d: Path) -> Path:
    return d / "SPARKY_VERSION"


def current(d: Path, version: str) -> bool:
    """Whether the runtime in d is the version this Sparky pins. Sticks made
    before 0.4 have no stamp, so running setup again upgrades them."""
    try:
        return _stamp(d).read_text().strip() == version
    except OSError:
        return False


def _running_from(d: Path) -> bool:
    try:
        Path(sys.executable).resolve().relative_to(d.resolve())
        return True
    except (ValueError, OSError):
        return False


def installed_targets(root: Path) -> list[str]:
    return [t for t in TARGETS if python_exe(root, t) and ollama_exe(root, t)]


def pylib_ready(root: Path) -> bool:
    return (root / "runtime" / "pylib" / "rich").is_dir()


def cache_dir() -> Path:
    """Downloads are kept beside the app that runs setup, so a second stick
    does not download them again. Safe to delete."""
    from .config import find_root
    d = find_root() / ".cache" / "downloads"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---- HTTP ---------------------------------------------------------------------------

def _open(url: str, headers: dict | None = None, timeout: float = 60):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)


def download(url: str, dest: Path, progress: Progress | None = None, label: str = "") -> Path:
    """Download to dest (via a .part file, so an interrupted download is never
    mistaken for a finished one)."""
    if dest.exists():
        return dest
    part = dest.with_name(dest.name + ".part")
    with _open(url) as resp, open(part, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done, last = 0, 0.0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress and time.monotonic() - last > 0.5:
                last = time.monotonic()
                pct = f"{done * 100 // total}% of {total / 1e6:.0f} MB" if total else f"{done / 1e6:.0f} MB"
                progress(f"downloading {label or dest.name}: {pct}")
    part.replace(dest)
    return dest


_SUMS: dict[str, dict[str, str]] = {}


def checksums(url: str) -> dict[str, str]:
    """A release's published SHA-256 list as {filename: hex}."""
    if url not in _SUMS:
        with _open(url) as resp:
            text = resp.read().decode("utf-8", "replace")
        sums = {}
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                sums[parts[-1].lstrip("*").lstrip("./")] = parts[0].lower()
        _SUMS[url] = sums
    return _SUMS[url]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verified_download(base: str, sums_name: str, asset: str, progress: Progress | None) -> Path:
    dest = cache_dir() / asset
    expected = checksums(f"{base}/{sums_name}").get(asset)
    if not expected:
        raise RuntimeError(f"{asset} is not in the release checksum list; refusing to use it")
    if dest.exists() and sha256(dest) != expected:
        dest.unlink()   # a stale or damaged cache entry
    download(f"{base}/{asset}", dest, progress, asset)
    got = sha256(dest)
    if got != expected:
        dest.unlink()
        raise RuntimeError(f"checksum mismatch for {asset} (expected {expected[:12]}, got {got[:12]})")
    return dest


class RangeFile(io.RawIOBase):
    """A read-only, seekable view of a remote file, fetched with HTTP range
    requests in blocks. Enough for zipfile to read the directory at the end
    of an archive and then just the members it is asked for."""

    BLOCK = 1 << 20

    def __init__(self, url: str):
        with _open(url, {"Range": "bytes=0-0"}) as resp:
            if resp.status != 206:
                raise OSError("the server does not support range requests")
            self.url = resp.url     # the redirect target, so later requests skip the redirect
            self.size = int(resp.headers["Content-Range"].rsplit("/", 1)[1])
        self.pos = 0
        self.blocks: dict[int, bytes] = {}

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos

    def seek(self, offset, whence=0):
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def _block(self, i: int) -> bytes:
        if i not in self.blocks:
            start = i * self.BLOCK
            end = min(start + self.BLOCK, self.size) - 1
            for attempt in range(3):
                try:
                    with _open(self.url, {"Range": f"bytes={start}-{end}"}) as resp:
                        self.blocks[i] = resp.read()
                    break
                except (urllib.error.URLError, OSError):
                    if attempt == 2:
                        raise
                    time.sleep(1 + attempt)
            if len(self.blocks) > 64:          # keep memory bounded
                self.blocks.pop(next(iter(self.blocks)))
        return self.blocks[i]

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        out = bytearray()
        while n > 0 and self.pos < self.size:
            i, off = divmod(self.pos, self.BLOCK)
            chunk = self._block(i)[off: off + n]
            out += chunk
            self.pos += len(chunk)
            n -= len(chunk)
        return bytes(out)

    def readinto(self, b):
        data = self.read(len(b))
        b[: len(data)] = data
        return len(data)


# ---- archives ---------------------------------------------------------------------------

def _is_gpu(name: str) -> bool:
    """Whether an archive member belongs to a GPU backend. Folder names end
    in "/", so a GPU folder matches as well as the files in it."""
    parts = name.replace("\\", "/").split("/")
    return any(p.lower().startswith(GPU_DIRS) for p in parts[:-1]) or \
        any(parts[-1].lower().startswith(f"libggml-{g}") or parts[-1].lower().startswith(f"ggml-{g}")
            for g in GPU_DIRS)


@contextlib.contextmanager
def _zstd_stream(path: Path):
    """A readable, decompressed stream of a .zst file, from whatever this
    computer has: Python 3.14's own zstd, the zstandard module, the zstd
    command, or as a last resort zstandard installed just for setup."""
    try:
        from compression import zstd  # type: ignore  # Python 3.14+
        with zstd.ZstdFile(path) as f:
            yield f
        return
    except ImportError:
        pass
    mod = _zstandard_module(install=False)
    if mod is None and shutil.which("zstd"):
        proc = subprocess.Popen(["zstd", "-dc", str(path)], stdout=subprocess.PIPE)
        try:
            yield proc.stdout
        finally:
            proc.stdout.close()
            if proc.wait() not in (0, -13):       # -13: we stopped reading early (SIGPIPE)
                raise RuntimeError("zstd could not unpack the archive")
        return
    mod = mod or _zstandard_module(install=True)
    with open(path, "rb") as raw, mod.ZstdDecompressor().stream_reader(raw) as f:
        yield f


def _zstandard_module(install: bool):
    try:
        import zstandard  # type: ignore
        return zstandard
    except ImportError:
        pass
    if not install:
        return None
    import importlib
    target = cache_dir().parent / "pylib-setup"
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                    "--target", str(target), "zstandard"], check=True)
    if str(target) not in sys.path:
        sys.path.insert(0, str(target))
    importlib.invalidate_caches()   # the folder is new; the import system cached its absence
    import zstandard  # type: ignore
    return zstandard


def _safe_member(name: str) -> bool:
    p = name.replace("\\", "/")
    return not (p.startswith("/") or ".." in p.split("/") or ":" in p.split("/")[0])


def _extract_tar(fileobj, dest: Path, skip: Callable[[str], bool], stream: bool) -> None:
    mode = "r|*" if stream else "r:*"
    with tarfile.open(fileobj=fileobj, mode=mode) as tar:
        for m in tar:
            # a folder entry is judged as a folder: "lib/ollama/cuda_v12" must
            # match like the files inside it, or an empty GPU folder is made
            name = m.name.rstrip("/") + ("/" if m.isdir() else "")
            if skip(name) or not _safe_member(m.name):
                continue
            if sys.version_info >= (3, 12):
                tar.extract(m, dest, filter="data")
            else:  # pragma: no cover
                tar.extract(m, dest)


def _copy_into(src: Path, dst: Path) -> None:
    """Copy a tree, turning symlinks into real files: exFAT and FAT cannot
    store links, and a stick must work on every OS."""
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, symlinks=False, dirs_exist_ok=True)


def _prune_python(d: Path) -> None:
    """Drop what a portable runtime never uses (tests, Tk, headers), roughly
    halving its size on the stick."""
    for rel in ("share", "include", "libs", "tcl", "Lib/test", "Lib/idlelib", "Lib/tkinter",
                "Lib/turtledemo", "Lib/lib2to3", "Lib/ensurepip", "Lib/pydoc_data"):
        shutil.rmtree(d / rel, ignore_errors=True)
    for lib in d.glob("lib/python3*"):
        for rel in ("test", "idlelib", "tkinter", "turtledemo", "lib2to3", "ensurepip", "pydoc_data"):
            shutil.rmtree(lib / rel, ignore_errors=True)
        for cfg in lib.glob("config-3*"):
            shutil.rmtree(cfg, ignore_errors=True)
    for pat in ("lib/libtcl*", "lib/libtk*", "lib/tcl*", "lib/tk*", "lib/itcl*", "lib/thread*",
                "DLLs/_tkinter*", "DLLs/tcl*", "DLLs/tk*"):
        for p in d.glob(pat):
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    # bin/python3 and bin/python are links to python3.12: copied as files they
    # would triple the binary, and the launchers call python3.12 directly
    for p in (d / "bin").glob("*"):
        if p.is_symlink():
            p.unlink()
    # libpython3.12.so is a link to the .so.1.0 the binary actually loads;
    # resolved into a copy it would add another 32 MB
    for p in d.glob("lib/libpython3*.so"):
        if p.is_symlink():
            p.unlink()


# ---- fetching --------------------------------------------------------------------------

def ensure_python(root: Path, target: str, progress: Progress | None = None) -> Path:
    exe = python_exe(root, target)
    if exe and current(python_dir(root, target), PBS_PY):
        return exe
    if exe and _running_from(python_dir(root, target)):
        # cannot replace the Python that is running this code (Windows locks
        # it); setup run from a checkout or another stick upgrades it
        return exe
    triple = TARGETS[target][0]
    asset = f"cpython-{PBS_PY}+{PBS_TAG}-{triple}-install_only_stripped.tar.gz"
    archive = verified_download(PBS_URL, "SHA256SUMS", asset, progress)
    _say(progress, f"unpacking Python for {target}")
    with tempfile.TemporaryDirectory() as tmp:
        with open(archive, "rb") as f:
            _extract_tar(f, Path(tmp), lambda n: False, stream=False)
        src = Path(tmp) / "python"
        _prune_python(src)
        dest = python_dir(root, target)
        shutil.rmtree(dest, ignore_errors=True)
        _copy_into(src, dest)
        _stamp(dest).write_text(PBS_PY + "\n")
    _say(progress, f"Python for {target} ready")
    return python_exe(root, target)  # type: ignore[return-value]


def ensure_ollama(root: Path, target: str, progress: Progress | None = None, gpu: bool = False) -> Path:
    exe = ollama_exe(root, target)
    if exe and current(ollama_dir(root, target), OLLAMA_TAG):
        return exe
    asset = TARGETS[target][1]
    skip = (lambda n: False) if gpu else _is_gpu
    dest = ollama_dir(root, target)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "ollama"
        out.mkdir()
        if asset.endswith(".zip") and not gpu:
            _say(progress, f"downloading the CPU files of Ollama for {target}")
            try:
                src = RangeFile(f"{OLLAMA_URL}/{asset}")
            except OSError:
                src = None
            if src is not None:
                _extract_zip(zipfile.ZipFile(src), out, skip)
            else:
                path = verified_download(OLLAMA_URL, "sha256sum.txt", asset, progress)
                _extract_zip(zipfile.ZipFile(path), out, skip)
        else:
            path = verified_download(OLLAMA_URL, "sha256sum.txt", asset, progress)
            _say(progress, f"unpacking Ollama for {target}")
            if asset.endswith(".zst"):
                with _zstd_stream(path) as stream:
                    _extract_tar(stream, out, skip, stream=True)
            elif asset.endswith(".zip"):
                _extract_zip(zipfile.ZipFile(path), out, skip)
            else:
                with open(path, "rb") as raw:
                    _extract_tar(raw, out, skip, stream=False)
        shutil.rmtree(dest, ignore_errors=True)
        _copy_into(out, dest)
        _stamp(dest).write_text(OLLAMA_TAG + "\n")
    _say(progress, f"Ollama for {target} ready")
    return ollama_exe(root, target)  # type: ignore[return-value]


def _extract_zip(z: zipfile.ZipFile, dest: Path, skip: Callable[[str], bool]) -> None:
    for info in z.infolist():
        if info.is_dir() or skip(info.filename) or not _safe_member(info.filename):
            continue
        out = dest / info.filename
        out.parent.mkdir(parents=True, exist_ok=True)
        with z.open(info) as src, open(out, "wb") as dst:   # zipfile checks each CRC-32
            shutil.copyfileobj(src, dst, 1 << 20)


def run_prefix(exe: Path) -> list[str]:
    """How to start a binary that lives on the stick. On a Linux mount that
    does not allow running programs (FAT, or noexec), the dynamic loader can
    still start it."""
    if hardware.os_name() == "linux" and not os.access(exe, os.X_OK):
        for ld in ("/lib64/ld-linux-x86-64.so.2", "/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2",
                   "/lib/ld-linux-aarch64.so.1", "/lib64/ld-linux-aarch64.so.1"):
            if os.path.exists(ld):
                return [ld, str(exe)]
    return [str(exe)]


def ensure_pylib(root: Path, progress: Progress | None = None) -> None:
    """The pure-Python libraries the terminal UI uses, shared by every OS.
    Installed with this computer's portable Python from the stick."""
    if pylib_ready(root):
        return
    exe = ensure_python(root, hardware.target(), progress)
    _say(progress, "installing the Python libraries (rich, prompt_toolkit)")
    # PYTHONNOUSERSITE and --ignore-installed: packages this computer happens
    # to have must not count as installed, or pip would leave them out and
    # the stick would lack them everywhere else
    env = {**os.environ, "PYTHONHOME": str(python_dir(root, hardware.target())), "PYTHONNOUSERSITE": "1"}
    env.pop("PYTHONPATH", None)
    with tempfile.TemporaryDirectory() as tmp:
        # pip into a temp folder first, then copy: pip writes links and
        # caches that a FAT or exFAT stick cannot hold
        subprocess.run(run_prefix(exe) + ["-s", "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                                          "--no-cache-dir", "--no-compile", "--ignore-installed",
                                          "--target", tmp, *PY_DEPS],
                       check=True, env=env)
        shutil.rmtree(Path(tmp) / "bin", ignore_errors=True)
        _copy_into(Path(tmp), root / "runtime" / "pylib")
    _say(progress, "Python libraries ready")


def ensure(root: Path, targets: list[str], progress: Progress | None = None, gpu: bool = False) -> None:
    """Everything needed to run on each target. The computer doing the work
    comes first, because its Python installs the shared libraries."""
    host = hardware.target()
    order = sorted(set(targets) | {host} if host in TARGETS else set(targets),
                   key=lambda t: (t != host, t))
    for t in order:
        if t not in TARGETS:
            raise ValueError(f"unknown target {t}; choose from {', '.join(TARGETS)}")
        ensure_python(root, t, progress)
        ensure_ollama(root, t, progress, gpu=gpu)
        if t == host:
            ensure_pylib(root, progress)


# ---- the model server ----------------------------------------------------------------

@contextlib.contextmanager
def server(root: Path, host: str, progress: Progress | None = None, reuse: bool = True):
    """Yield with a model server running for this stick: the one already
    running (the launcher starts one), or a temporary one stopped on exit.
    reuse=False always starts a fresh one, for setup, which must pull into
    this stick and not into whichever stick's server holds the usual port."""
    from .ollama import OllamaClient

    client = OllamaClient(host)
    if client.reachable():
        if reuse:
            yield client
            return
        raise RuntimeError(f"something is already using {host}")
    exe = ollama_exe(root, hardware.target())
    if exe is None:
        raise RuntimeError(f"this stick has no model server for {hardware.target()}; "
                           f"run setup to add it")
    env = server_env(root, host)
    log = open(root / "data" / "ollama.log", "ab") if (root / "data").is_dir() else subprocess.DEVNULL
    _say(progress, "starting the model server")
    # its own process group or session: a Ctrl-C in the terminal is for the
    # wizard (which then stops the server cleanly), not for the server itself
    extra = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    proc = subprocess.Popen(run_prefix(exe) + ["serve"], env=env, stdout=log, stderr=log,
                            stdin=subprocess.DEVNULL, cwd=str(root), **extra)
    try:
        for _ in range(120):
            if client.reachable(timeout=1):
                break
            if proc.poll() is not None:
                raise RuntimeError("the model server stopped while starting; see data/ollama.log")
            time.sleep(0.25)
        else:
            raise RuntimeError("the model server did not start within 30 seconds")
        yield client
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        if log is not subprocess.DEVNULL:
            log.close()


def server_env(root: Path, host: str) -> dict:
    """The model server's environment: its models and keys on the stick,
    nothing in the host computer's home folder."""
    exe = ollama_exe(root, hardware.target())
    env = dict(os.environ)
    home = root / "data" / "home"
    home.mkdir(parents=True, exist_ok=True)
    env.update({
        "OLLAMA_MODELS": str(root / "runtime" / "ollama" / "models"),
        "OLLAMA_HOST": host.split("://", 1)[-1],
        "HOME": str(home),
        "USERPROFILE": str(home),
    })
    if exe is not None and hardware.os_name() == "linux":
        lib = exe.parent.parent / "lib" / "ollama"
        # no trailing ":" when the variable was empty: an empty entry means
        # the current folder, which would let a library planted there load
        existing = env.get("LD_LIBRARY_PATH")
        env["LD_LIBRARY_PATH"] = f"{lib}:{existing}" if existing else str(lib)
    return env
