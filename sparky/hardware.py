"""What this computer and the stick can handle: memory, CPU, drives, filesystems.

Stdlib only, on every OS. The numbers feed the model recommender and `doctor`;
the drive list feeds the setup wizard. Every probe degrades to "unknown"
rather than raising, because a wrong guess here must never stop Sparky
from starting.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

GB = 1024 ** 3


# ---- this computer -----------------------------------------------------------

def os_name() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return "unknown"


def arch() -> str:
    m = platform.machine().lower()
    if m in ("x86_64", "amd64", "x64"):
        return "x86_64"
    if m in ("aarch64", "arm64", "armv8l"):
        return "aarch64"
    return m or "unknown"


def target() -> str:
    """The runtime folder name for this computer, e.g. linux-x86_64."""
    return f"{os_name()}-{arch()}"


def total_ram_gb() -> float:
    """Installed memory in GB, or 0.0 when it cannot be read."""
    try:
        if os_name() == "linux":
            return _meminfo("MemTotal")
        if os_name() == "macos":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                                 text=True, timeout=5).stdout.strip()
            return int(out) / GB
        if os_name() == "windows":
            return _win_memory()[0]
    except Exception:
        pass
    return 0.0


def available_ram_gb() -> float:
    """Memory free for a model right now, or 0.0 when unknown."""
    try:
        if os_name() == "linux":
            return _meminfo("MemAvailable")
        if os_name() == "windows":
            return _win_memory()[1]
        if os_name() == "macos":
            # macOS reclaims inactive and purgeable pages on demand, so
            # "free" badly understates what a model can use. Total minus the
            # wired and compressed pages is the honest figure.
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
            page = int(re.search(r"page size of (\d+)", out).group(1))
            pages = {k: int(v) for k, v in re.findall(r"Pages ([\w ]+?):\s+(\d+)", out)}
            used = pages.get("wired down", 0) + pages.get("occupied by compressor", 0)
            return max(total_ram_gb() - used * page / GB, 0.0)
    except Exception:
        pass
    return 0.0


def _meminfo(key: str) -> float:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith(key + ":"):
            return int(line.split()[1]) * 1024 / GB
    return 0.0


def _win_memory() -> tuple[float, float]:
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]

    st = MEMORYSTATUSEX()
    st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))  # type: ignore[attr-defined]
    return st.ullTotalPhys / GB, st.ullAvailPhys / GB


def cpu_count() -> int:
    return os.cpu_count() or 1


def accelerator() -> str:
    """A short note on GPU help. Apple Silicon gets Metal from the bundled
    Ollama; the portable bundle is CPU-only elsewhere to keep it small."""
    if os_name() == "macos" and arch() == "aarch64":
        return "Apple Silicon GPU (Metal)"
    return "CPU"


# ---- drives ------------------------------------------------------------------

@dataclass
class Drive:
    path: Path          # mountpoint or drive root, e.g. /media/ann/Sparky or E:\
    label: str
    fstype: str         # lower-case: exfat, vfat, ntfs, apfs, ext4 ...
    total_gb: float
    free_gb: float
    removable: bool

    def describe(self) -> str:
        name = self.label or str(self.path)
        return (f"{name} ({self.path}), {self.fstype or 'unknown format'}, "
                f"{self.free_gb:.1f} GB free of {self.total_gb:.1f} GB")


def free_gb(path: Path) -> float:
    try:
        return shutil.disk_usage(path).free / GB
    except OSError:
        return 0.0


def fstype(path: Path) -> str:
    """Filesystem type of the volume holding `path`, lower-case, or ''."""
    path = Path(path)
    try:
        if os_name() == "linux":
            best, kind = "", ""
            for mnt, typ in _linux_mounts():
                if (str(path) + "/").startswith(mnt.rstrip("/") + "/") and len(mnt) > len(best):
                    best, kind = mnt, typ
            return _normalise_fs(kind)
        if os_name() == "macos":
            for mnt, typ in _mac_mounts():
                if str(path) == mnt or str(path).startswith(mnt.rstrip("/") + "/"):
                    if mnt != "/":
                        return _normalise_fs(typ)
            return "apfs"
        if os_name() == "windows":
            return _win_volume(str(path.anchor or path))[1]
    except Exception:
        pass
    return ""


def _normalise_fs(kind: str) -> str:
    kind = kind.lower()
    if kind in ("msdos", "fat", "fat32", "vfat"):
        return "vfat"
    if kind in ("fuseblk", "ntfs3", "ntfs-3g"):
        return "ntfs"
    return kind


def _linux_mounts() -> list[tuple[str, str]]:
    out = []
    try:
        for line in Path("/proc/mounts").read_text().splitlines():
            parts = line.split()
            if len(parts) >= 3:
                out.append((parts[1].replace("\\040", " "), parts[2]))
    except OSError:
        pass
    return out


def _mac_mounts() -> list[tuple[str, str]]:
    out = []
    try:
        text = subprocess.run(["mount"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return out
    # "/dev/disk4s1 on /Volumes/Sparky (exfat, local, nodev, nosuid, noowners)"
    for m in re.finditer(r"^\S+ on (.+) \(([\w-]+)", text, re.MULTILINE):
        out.append((m.group(1), m.group(2)))
    return out


def _win_volume(root: str) -> tuple[str, str]:
    import ctypes

    label = ctypes.create_unicode_buffer(261)
    fs = ctypes.create_unicode_buffer(261)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(  # type: ignore[attr-defined]
        ctypes.c_wchar_p(root), label, 261, None, None, None, fs, 261)
    if not ok:
        return "", ""
    return label.value, _normalise_fs(fs.value)


def list_drives() -> list[Drive]:
    """Drives a stick could be: removable ones first, then other external
    volumes. The system disk is left out."""
    try:
        if os_name() == "linux":
            drives = _linux_drives()
        elif os_name() == "macos":
            drives = _mac_drives()
        elif os_name() == "windows":
            drives = _win_drives()
        else:
            drives = []
    except Exception:
        drives = []
    return sorted(drives, key=lambda d: (not d.removable, d.label.lower()))


def _usage(path: Path) -> tuple[float, float]:
    try:
        u = shutil.disk_usage(path)
        return u.total / GB, u.free / GB
    except OSError:
        return 0.0, 0.0


def _linux_drives() -> list[Drive]:
    removable = _linux_removable_mounts()
    out = []
    for mnt, typ in _linux_mounts():
        if not mnt.startswith(("/media/", "/run/media/", "/mnt/")):
            continue
        total, free = _usage(Path(mnt))
        out.append(Drive(Path(mnt), Path(mnt).name, _normalise_fs(typ), total, free,
                         mnt in removable or mnt.startswith(("/media/", "/run/media/"))))
    return out


def _linux_removable_mounts() -> set[str]:
    try:
        import json
        text = subprocess.run(["lsblk", "-J", "-o", "MOUNTPOINT,RM,HOTPLUG"],
                              capture_output=True, text=True, timeout=5).stdout
        found: set[str] = set()

        def walk(nodes):
            for n in nodes or []:
                if n.get("mountpoint") and (str(n.get("rm")) in ("1", "True", "true")
                                            or str(n.get("hotplug")) in ("1", "True", "true")):
                    found.add(n["mountpoint"])
                walk(n.get("children"))

        walk(json.loads(text).get("blockdevices"))
        return found
    except Exception:
        return set()


def _mac_drives() -> list[Drive]:
    out = []
    mounts = dict(_mac_mounts())
    vols = Path("/Volumes")
    for p in sorted(vols.iterdir()) if vols.exists() else []:
        try:
            if p.is_symlink() or os.path.realpath(p) == "/":
                continue  # the boot volume appears here as a link to /
        except OSError:
            continue
        total, free = _usage(p)
        out.append(Drive(p, p.name, _normalise_fs(mounts.get(str(p), "")), total, free, True))
    return out


def _win_drives() -> list[Drive]:
    import ctypes
    import string

    k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    mask = k32.GetLogicalDrives()
    system = os.environ.get("SystemDrive", "C:").upper().rstrip("\\")
    out = []
    for i, letter in enumerate(string.ascii_uppercase):
        if not mask & (1 << i):
            continue
        root = f"{letter}:\\"
        kind = k32.GetDriveTypeW(ctypes.c_wchar_p(root))
        if kind not in (2, 3) or f"{letter}:" == system:   # 2 removable, 3 fixed
            continue
        label, fs = _win_volume(root)
        total, free = _usage(Path(root))
        if total == 0:
            continue   # empty card reader slot
        out.append(Drive(Path(root), label, fs, total, free, kind == 2))
    return out


# ---- filesystem advice ---------------------------------------------------------

def fs_problem(kind: str) -> str | None:
    """Why a filesystem won't do for a stick, or None if it is fine."""
    if kind == "vfat":
        return ("This drive is FAT32. FAT32 cannot hold files over 4 GB (most models are "
                "bigger) and on Linux it cannot run the model server. Reformat it as exFAT.")
    return None


def fs_warning(kind: str) -> str | None:
    """A softer note: works, but not everywhere."""
    if kind == "ntfs":
        return "NTFS works on Windows and Linux, but macOS can only read it. exFAT works everywhere."
    if kind in ("apfs", "hfs"):
        return "This drive is formatted for Macs only. exFAT works on every computer."
    if kind in ("ext4", "ext3", "btrfs", "xfs"):
        return "This drive is formatted for Linux only. exFAT works on every computer."
    return None


def exfat_steps() -> str:
    return (
        "How to format a stick as exFAT (this erases it):\n"
        "  Windows: File Explorer, right-click the stick, Format, File system exFAT, name it Sparky.\n"
        "  macOS:   Disk Utility, select the stick, Erase, Format ExFAT, name it Sparky.\n"
        "  Linux:   Disks app, select the stick, Format Partition, Other, exFAT, name it Sparky,\n"
        "           or run: sudo tools/format_exfat.sh  (keeps the files already on it)."
    )
