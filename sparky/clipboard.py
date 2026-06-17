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
        # osascript fallback: write clipboard PNG to a temp file
        tmp = os.path.join(tempfile.gettempdir(), "sparky_clip.png")
        script = (
            'try\nset f to (open for access POSIX file "%s" with write permission)\n'
            "write (the clipboard as «class PNGf») to f\nclose access f\nend try" % tmp
        )
        _run_text(["osascript", "-e", script])
        if os.path.exists(tmp) and os.path.getsize(tmp) > 8:
            with open(tmp, "rb") as fh:
                return fh.read(), "image/png"
    # ----- Windows -----
    if os.name == "nt":
        tmp = os.path.join(tempfile.gettempdir(), "sparky_clip.png")
        ps = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$i=[Windows.Forms.Clipboard]::GetImage();"
            "if($i){$i.Save('%s',[System.Drawing.Imaging.ImageFormat]::Png)}" % tmp.replace("\\", "\\\\")
        )
        _run_text(["powershell", "-NoProfile", "-Command", ps])
        if os.path.exists(tmp) and os.path.getsize(tmp) > 8:
            with open(tmp, "rb") as fh:
                return fh.read(), "image/png"
    return None


def available() -> bool:
    """Whether a clipboard image tool is present on this OS."""
    if sys.platform == "darwin" or os.name == "nt":
        return True
    return bool((os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"))
                or (os.environ.get("DISPLAY") and shutil.which("xclip")))
