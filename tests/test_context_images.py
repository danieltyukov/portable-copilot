import base64
from pathlib import Path

from sparky import context, images


def test_load_context_includes_dropped_file(tmp_path):
    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    (ctx_dir / "notes.md").write_text("project uses Go and Postgres")
    out = context.load_context(ctx_dir)
    assert "notes.md" in out
    assert "Go and Postgres" in out


def test_load_context_empty(tmp_path):
    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    assert context.load_context(ctx_dir) == ""


def test_find_and_encode_image(tmp_path):
    # a 1x1 PNG
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )
    img = tmp_path / "shot.png"
    img.write_bytes(png)
    found = images.find_image_paths(f"explain {img}", cwd=tmp_path)
    assert str(img) in found
    block = images.encode_image(img)
    assert block["type"] == "image"
    assert block["source"]["media_type"] == "image/png"
    assert base64.b64decode(block["source"]["data"]) == png


def test_find_image_ignores_missing(tmp_path):
    assert images.find_image_paths("see nope.png", cwd=tmp_path) == []
