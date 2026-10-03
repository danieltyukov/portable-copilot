from sparky import config


def test_defaults_when_no_env_file(tmp_path):
    cfg = config.load(root=tmp_path)
    assert cfg.model == ""            # choose from what is installed
    assert cfg.mode == "chat"
    assert cfg.ctx == 0 and cfg.think is False and cfg.yolo is False
    assert cfg.context_dir == tmp_path / "context"
    assert cfg.models_dir == tmp_path / "runtime" / "ollama" / "models"
    assert cfg.ollama_host == config.DEFAULT_OLLAMA_HOST


def test_reads_env_file_with_inline_comments(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "sparky.env").write_text(
        "SPARKY_MODEL=gemma3:4b   # what to open with\nSPARKY_MODE=code\nSPARKY_CTX=12000\n"
        "SPARKY_THINK=1\nSPARKY_YOLO=yes\n")
    cfg = config.load(root=tmp_path)
    assert cfg.model == "gemma3:4b"
    assert cfg.mode == "code"
    assert cfg.ctx == 12000
    assert cfg.think is True and cfg.yolo is True


def test_environment_beats_the_file(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "sparky.env").write_text("SPARKY_MODEL=a:1b\n")
    monkeypatch.setenv("SPARKY_MODEL", "b:2b")
    assert config.load(root=tmp_path).model == "b:2b"


def test_legacy_tier_settings_still_work(tmp_path):
    # sticks set up before 0.4 used fast/max tiers
    (tmp_path / "data").mkdir()
    env = tmp_path / "data" / "sparky.env"
    env.write_text("SPARKY_FAST_MODEL=qwen3.5:4b\nSPARKY_MAX_MODEL=qwen3-coder:30b\n")
    cfg = config.load(root=tmp_path)
    assert cfg.model == "qwen3-coder:30b"
    assert (cfg.legacy_fast, cfg.legacy_max) == ("qwen3.5:4b", "qwen3-coder:30b")
    env.write_text("SPARKY_FAST_MODEL=qwen3.5:4b\nSPARKY_MAX_MODEL=qwen3-coder:30b\nSPARKY_TIER=fast\n")
    assert config.load(root=tmp_path).model == "qwen3.5:4b"


def test_unknown_mode_and_bad_ctx_fall_back(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "sparky.env").write_text("SPARKY_MODE=painting\nSPARKY_CTX=lots\n")
    cfg = config.load(root=tmp_path)
    assert cfg.mode == "chat" and cfg.ctx == 0


def test_write_env_roundtrip_and_remove(tmp_path):
    cfg = config.load(root=tmp_path)
    config.write_env(cfg, {"SPARKY_MODEL": "x:1b", "SPARKY_TIER": "max"})
    config.write_env(cfg, {"SPARKY_MODE": "write"}, remove=("SPARKY_TIER",))
    text = cfg.env_file.read_text()
    assert "SPARKY_TIER" not in text
    again = config.load(root=tmp_path)
    assert again.model == "x:1b" and again.mode == "write"


def test_ollama_host_gets_scheme(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11500")
    assert config.load(root=tmp_path).ollama_host == "http://127.0.0.1:11500"


def test_context_window(tmp_path):
    cfg = config.load(root=tmp_path)
    assert config.context_window(cfg, 8) == 8192
    assert config.context_window(cfg, 64) == 16384
    cfg.ctx = 4096
    assert config.context_window(cfg, 64) == 4096
