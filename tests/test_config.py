from sparky import config


def test_defaults_when_no_env_file(tmp_path):
    cfg = config.load(root=tmp_path)
    assert cfg.anthropic_api_key is None
    assert cfg.model == config.DEFAULT_MODEL
    assert cfg.local_model == config.DEFAULT_LOCAL_MODEL
    assert cfg.yolo is False
    assert cfg.context_dir == tmp_path / "context"


def test_reads_env_file(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "sparky.env").write_text(
        'ANTHROPIC_API_KEY="sk-test-123"\nSPARKY_MODEL=claude-opus-4-8\nSPARKY_YOLO=1\n'
    )
    cfg = config.load(root=tmp_path)
    assert cfg.anthropic_api_key == "sk-test-123"
    assert cfg.model == "claude-opus-4-8"
    assert cfg.yolo is True


def test_write_env_roundtrip(tmp_path):
    cfg = config.load(root=tmp_path)
    config.write_env(cfg, {"ANTHROPIC_API_KEY": "sk-abc"})
    again = config.load(root=tmp_path)
    assert again.anthropic_api_key == "sk-abc"
