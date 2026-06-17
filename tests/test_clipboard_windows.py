"""Unit-test the Windows clipboard grab branch by faking the PowerShell call,
since real Windows/PowerShell isn't available in CI/dev."""
import base64
import re

from sparky import clipboard

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _path_from_save_cmd(cmd):
    """Extract the file path from a `...Save('PATH',...)` PowerShell command."""
    joined = " ".join(cmd)
    m = re.search(r"Save\('([^']+)'", joined)
    return m.group(1) if m else None


def test_windows_grab_screenshot(monkeypatch):
    monkeypatch.setattr(clipboard.os, "name", "nt")

    def fake_run_text(cmd):
        if "GetImage" in " ".join(cmd) and "Save(" in " ".join(cmd):
            path = _path_from_save_cmd(cmd)
            with open(path, "wb") as fh:        # simulate PS saving the clipboard PNG
                fh.write(PNG)
        return ""

    monkeypatch.setattr(clipboard, "_run_text", fake_run_text)
    got = clipboard.grab_image()
    assert got is not None
    data, media = got
    assert media == "image/png"
    assert data == PNG


def test_windows_grab_nothing(monkeypatch):
    monkeypatch.setattr(clipboard.os, "name", "nt")
    monkeypatch.setattr(clipboard, "_run_text", lambda cmd: "")  # PS writes nothing
    assert clipboard.grab_image() is None


def test_windows_grab_file_drop(tmp_path, monkeypatch):
    img = tmp_path / "shot.jpg"
    img.write_bytes(PNG)
    monkeypatch.setattr(clipboard.os, "name", "nt")

    def fake_run_text(cmd):
        if "GetFileDropList" in " ".join(cmd):
            return str(img)        # simulate a copied image file in Explorer
        return ""

    monkeypatch.setattr(clipboard, "_run_text", fake_run_text)
    got = clipboard.grab_image()
    assert got is not None
    data, media = got
    assert media == "image/jpeg"   # .jpg -> jpeg, not mislabeled png
    assert data == PNG
