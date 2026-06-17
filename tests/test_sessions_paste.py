import base64

from sparky import config, sessions, images


def test_session_save_load_and_title(tmp_path):
    cfg = config.load(root=tmp_path)
    history = [
        {"role": "user", "content": [{"type": "text", "text": "build me a parser"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "sure"}]},
    ]
    sessions.save(cfg, "20260617-120000", history)
    items = sessions.list_sessions(cfg)
    assert len(items) == 1
    assert items[0]["title"].startswith("build me a parser")
    assert sessions.latest(cfg)["history"] == history


def test_session_strips_image_data(tmp_path):
    cfg = config.load(root=tmp_path)
    history = [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}},
        {"type": "text", "text": "what is this"},
    ]}]
    sessions.save(cfg, "s1", history)
    loaded = sessions.latest(cfg)["history"]
    blocks = loaded[0]["content"]
    assert all(b["type"] != "image" for b in blocks)        # image data not persisted
    assert any("image from earlier" in b.get("text", "") for b in blocks)


def test_encode_image_bytes_roundtrip():
    block = images.encode_image_bytes(b"\x89PNGxyz", "image/png")
    assert block["type"] == "image"
    assert block["source"]["media_type"] == "image/png"
    assert base64.b64decode(block["source"]["data"]) == b"\x89PNGxyz"


def test_no_sessions_when_empty(tmp_path):
    cfg = config.load(root=tmp_path)
    assert sessions.latest(cfg) is None
    sessions.save(cfg, "x", [])           # empty history -> no file written
    assert sessions.list_sessions(cfg) == []
