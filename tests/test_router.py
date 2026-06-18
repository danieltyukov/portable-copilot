from sparky import config
from sparky.router import Router
from sparky.providers.base import ProviderError, Reply, text_block


class FakeLocal:
    """Local-provider stub. Raises ProviderError when asked to run a model in
    `raise_for` (simulating an OOM/load failure for a given tier). For streaming,
    a model in `stream_then_raise` emits one chunk before failing."""
    def __init__(self, raise_for=(), stream_then_raise=()):
        self.model = "?"
        self.raise_for = set(raise_for)
        self.stream_then_raise = set(stream_then_raise)
        self.calls = []

    def set_model(self, model):
        self.model = model

    def chat(self, messages, tools=None, system=None):
        self.calls.append(self.model)
        if self.model in self.raise_for:
            raise ProviderError("oom")
        return Reply(text=self.model, tool_calls=[], content_blocks=[text_block(self.model)])

    def chat_stream(self, messages, tools=None, system=None, on_text=None):
        self.calls.append(self.model)
        if self.model in self.stream_then_raise:
            if on_text:
                on_text("partial ")
            raise ProviderError("died mid-stream")
        if self.model in self.raise_for:
            raise ProviderError("oom")
        if on_text:
            on_text(self.model)
        return Reply(text=self.model, tool_calls=[], content_blocks=[text_block(self.model)])


def _router(tmp_path, **kw):
    cfg = config.load(root=tmp_path)
    return cfg, Router(cfg, local=FakeLocal(**kw))


def test_default_tier_is_max(tmp_path):
    cfg, r = _router(tmp_path)
    reply, backend = r.chat([], system=None)
    assert reply.text == cfg.max_model
    assert backend == f"qwen:{cfg.max_model}"
    assert r.last_fallback is False


def test_set_tier_fast(tmp_path):
    cfg, r = _router(tmp_path)
    r.set_tier("fast")
    reply, backend = r.chat([], system=None)
    assert reply.text == cfg.fast_model
    assert backend == f"qwen:{cfg.fast_model}"


def test_tier_aliases(tmp_path):
    cfg, r = _router(tmp_path)
    assert r.set_tier("haiku") == "fast"
    assert r.set_tier("opus") == "max"
    assert r.set_tier("sonnet") == "max"


def test_max_load_failure_downgrades_to_fast(tmp_path):
    cfg = config.load(root=tmp_path)
    r = Router(cfg, local=FakeLocal(raise_for=[cfg.max_model]))  # max can't load
    reply, backend = r.chat([], system=None)
    assert reply.text == cfg.fast_model       # fell back to fast
    assert r.last_fallback is True
    assert "downgraded" in backend


def test_fast_failure_propagates(tmp_path):
    cfg = config.load(root=tmp_path)
    r = Router(cfg, local=FakeLocal(raise_for=[cfg.fast_model]))
    r.set_tier("fast")
    try:
        r.chat([], system=None)
        assert False, "expected ProviderError"
    except ProviderError:
        pass
    assert r.last_fallback is False


def test_stream_downgrades_before_any_text(tmp_path):
    cfg = config.load(root=tmp_path)
    r = Router(cfg, local=FakeLocal(raise_for=[cfg.max_model]))
    chunks = []
    reply, backend = r.chat_stream([], on_text=chunks.append)
    assert reply.text == cfg.fast_model
    assert r.last_fallback is True
    assert chunks == [cfg.fast_model]  # only the fast tier's text streamed


def test_stream_no_downgrade_after_text(tmp_path):
    cfg = config.load(root=tmp_path)
    # max streams a partial chunk then dies — must NOT retry (would double-render)
    r = Router(cfg, local=FakeLocal(stream_then_raise=[cfg.max_model]))
    try:
        r.chat_stream([], on_text=lambda t: None)
        assert False, "expected ProviderError"
    except ProviderError:
        pass
    assert r.last_fallback is False
