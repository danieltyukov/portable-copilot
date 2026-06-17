"""Grab an image from the system clipboard, cross-platform.

Lets you paste a screenshot into Sparky like Claude Code does. Uses whatever
clipboard tool the OS provides; returns raw image bytes + media type, or None.
  Linux  : wl-paste (Wayland) or xclip (X11)
  macOS  : pngpaste, else osascript
  Windows: PowerShell Get-Clipboard -Format Image
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

_IMG_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")


def _run(cmd: list[str]) -> bytes | None:
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=10)
        return out.stdout if out.returncode == 0 and out.stdout else None
    except (OSError, subprocess.SubprocessError):
        return None


def _run_text(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=10, text=True)
        return out.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def grab_image() -> tuple[bytes, str] | None:
    """Return (image_bytes, media_type) from the clipboard, or None."""
    # ----- Linux: Wayland -----
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
        types = _run_text(["wl-paste", "--list-types"])
        for mt in _IMG_TYPES:
            if mt in types:
                data = _run(["wl-paste", "--type", mt])
                if data:
                    return data, mt
    # ----- Linux: X11 -----
    if os.environ.get("DISPLAY") and shutil.which("xclip"):
        for mt in _IMG_TYPES:
            data = _run(["xclip", "-selection", "clipboard", "-t", mt, "-o"])
            if data and len(data) > 8:
                return data, mt
    # ----- macOS -----
    if sys.platform == "darwin":
        if shutil.which("pngpaste"):
            data = _run(["pngpaste", "-"])
            if data:
                return data, "image/png"
        tmp = _fresh_tmp()
        script = (
            'try\nset f to (open for access POSIX file "%s" with write permission)\n'
            "write (the clipboard as «class PNGf») to f\nclose access f\nend try" % tmp
        )
        _run_text(["osascript", "-e", script])
        return _read_tmp(tmp, "image/png")
    # ----- Windows -----
    if os.name == "nt":
        return _grab_windows()
    return None


def _fresh_tmp() -> str:
    fd, tmp = tempfile.mkstemp(suffix=".png", prefix="sparky_clip_")
    os.close(fd)
    try:
        os.remove(tmp)  # PS/osascript recreates it only if there really is an image
    except OSError:
        pass
    return tmp


def _read_tmp(path: str, media: str) -> tuple[bytes, str] | None:
    if os.path.exists(path) and os.path.getsize(path) > 8:
        with open(path, "rb") as fh:
            data = fh.read()
        try:
            os.remove(path)
        except OSError:
            pass
        return data, media
    return None


def _grab_windows() -> tuple[bytes, str] | None:
    tmp = _fresh_tmp()
    esc = tmp.replace("\\", "\\\\")
    # 1) a copied bitmap/screenshot -> save as PNG
    ps_img = (
        "$ErrorActionPreference='SilentlyContinue';"
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        "$i=[System.Windows.Forms.Clipboard]::GetImage();"
        f"if($i){{$i.Save('{esc}',[System.Drawing.Imaging.ImageFormat]::Png)}}"
    )
    _run_text(["powershell", "-NoProfile", "-Sta", "-Command", ps_img])
    got = _read_tmp(tmp, "image/png")
    if got:
        return got
    # 2) a copied image FILE in Explorer -> return its bytes with the right type
    ps_path = (
        "$ErrorActionPreference='SilentlyContinue';"
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$f=[System.Windows.Forms.Clipboard]::GetFileDropList();"
        "if($f -and $f.Count -ge 1){[Console]::Out.Write($f[0])}"
    )
    p = _run_text(["powershell", "-NoProfile", "-Sta", "-Command", ps_path]).strip()
    if p and os.path.isfile(p):
        ext = os.path.splitext(p)[1].lower()
        media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/png"}.get(ext)
        if media:
            with open(p, "rb") as fh:
                return fh.read(), media
    return None


def available() -> bool:
    """Whether a clipboard image tool is present on this OS."""
    if sys.platform == "darwin" or os.name == "nt":
        return True
    return bool((os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"))
                or (os.environ.get("DISPLAY") and shutil.which("xclip")))
