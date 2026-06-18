from sparky import config


def test_defaults_when_no_env_file(tmp_path):
    cfg = config.load(root=tmp_path)
    assert cfg.fast_model == config.DEFAULT_FAST_MODEL
    assert cfg.max_model == config.DEFAULT_MAX_MODEL
    assert cfg.tier == config.DEFAULT_TIER == "max"
    assert cfg.model == config.DEFAULT_MAX_MODEL  # default tier resolves to max
    assert cfg.yolo is False
    assert cfg.context_dir == tmp_path / "context"


def test_tiers_and_model_for_tier(tmp_path):
    cfg = config.load(root=tmp_path)
    assert cfg.tiers == [("fast", cfg.fast_model), ("max", cfg.max_model)]
    assert cfg.model_for_tier("fast") == cfg.fast_model
    assert cfg.model_for_tier("max") == cfg.max_model
    # aliases resolve through model_for_tier too
    assert cfg.model_for_tier("haiku") == cfg.fast_model
    assert cfg.model_for_tier("opus") == cfg.max_model


def test_normalize_tier_aliases():
    assert config.normalize_tier("haiku") == "fast"
    assert config.normalize_tier("sonnet") == "max"
    assert config.normalize_tier("opus") == "max"
    assert config.normalize_tier("FAST") == "fast"
    assert config.normalize_tier("bogus", default="fast") == "fast"
    assert config.normalize_tier(None) == config.DEFAULT_TIER


def test_reads_env_file(tmp_path):
    # swapping models for a different-size stick is just env overrides
    data = tmp_path / "data"
    data.mkdir()
    (data / "sparky.env").write_text(
        "SPARKY_FAST_MODEL=qwen3.5:2b\nSPARKY_MAX_MODEL=qwen3.6:27b\nSPARKY_TIER=fast\nSPARKY_YOLO=1\n"
    )
    cfg = config.load(root=tmp_path)
    assert cfg.fast_model == "qwen3.5:2b"
    assert cfg.max_model == "qwen3.6:27b"
    assert cfg.tier == "fast"
    assert cfg.model == "qwen3.5:2b"
    assert cfg.yolo is True


def test_write_env_roundtrip(tmp_path):
    cfg = config.load(root=tmp_path)
    config.write_env(cfg, {"SPARKY_TIER": "fast"})
    again = config.load(root=tmp_path)
    assert again.tier == "fast"


def test_ollama_host_gets_scheme(tmp_path, monkeypatch):
    # launcher sets OLLAMA_HOST as bare host:port; config must add a scheme
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11500")
    cfg = config.load(root=tmp_path)
    assert cfg.ollama_host == "http://127.0.0.1:11500"
