import base64

from sparky import context, images

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def test_load_context_includes_dropped_file(tmp_path):
    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    (ctx_dir / "notes.md").write_text("project uses Go and Postgres")
    (ctx_dir / "README.txt").write_text("the seeded instructions")
    (ctx_dir / ".hidden").mkdir()
    (ctx_dir / ".hidden" / "secret.md").write_text("do not include")
    out = context.load_context(ctx_dir)
    assert "notes.md" in out and "Go and Postgres" in out
    assert "seeded instructions" not in out and "do not include" not in out


def test_load_context_empty_or_missing(tmp_path):
    (tmp_path / "context").mkdir()
    assert context.load_context(tmp_path / "context") == ""
    assert context.load_context(tmp_path / "nope") == ""


def test_load_context_stays_within_budget(tmp_path):
    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    for i in range(5):
        (ctx_dir / f"f{i}.txt").write_text("word " * 2000)
    out = context.load_context(ctx_dir, max_chars=6000)
    assert len(out) < 7000
    assert "(not loaded)" in out
    assert "read_file" in out          # modes with tools can open the rest
    no_tools = context.load_context(ctx_dir, max_chars=6000, can_read=False)
    assert "read_file" not in no_tools and "Study mode" in no_tools


def test_find_and_encode_image(tmp_path):
    img = tmp_path / "shot.png"
    img.write_bytes(PNG)
    found = images.find_image_paths(f"explain {img}", cwd=tmp_path)
    assert str(img) in found
    block = images.encode_image(img)
    assert block["type"] == "image"
    assert block["source"]["media_type"] == "image/png"
    assert base64.b64decode(block["source"]["data"]) == PNG


def test_find_image_ignores_missing(tmp_path):
    assert images.find_image_paths("see nope.png", cwd=tmp_path) == []
