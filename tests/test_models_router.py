from sparky import config
from sparky.models import ModelManager
from sparky.ollama import OllamaClient
from sparky.providers.base import ModelNotFound, ProviderError, Reply, text_block
from sparky.router import Router


def _cfg(tmp_path, url, **env):
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "sparky.env").write_text("".join(f"{k}={v}\n" for k, v in env.items()))
    cfg = config.load(root=tmp_path)
    cfg.ollama_host = url
    return cfg


def test_installed_skips_embedding_models_and_sorts(tmp_path, fake_ollama):
    m = ModelManager(_cfg(tmp_path, fake_ollama.url))
    assert m.names() == ["gemma3:1b", "qwen3.5:4b"]


def test_resolve_names(tmp_path, fake_ollama):
    fake_ollama.models.append({"name": "gemma3:4b", "size": 3_300_000_000, "details": {}})
    m = ModelManager(_cfg(tmp_path, fake_ollama.url))
    assert m.resolve("qwen3.5:4b") == "qwen3.5:4b"
    assert m.resolve("qwen") == "qwen3.5:4b"          # unique prefix
    assert m.resolve("gemma3") is None                # ambiguous: 1b and 4b
    assert m.resolve("gemma3:1") == "gemma3:1b"
    assert m.resolve("fast") == "gemma3:1b"           # smallest
    assert m.resolve("max") == "qwen3.5:4b"           # largest
    assert m.resolve("llama") is None


def test_default_prefers_configured_then_catalog_rank(tmp_path, fake_ollama):
    assert ModelManager(_cfg(tmp_path, fake_ollama.url)).default() == "qwen3.5:4b"
    assert ModelManager(_cfg(tmp_path, fake_ollama.url, SPARKY_MODEL="gemma3:1b")).default() == "gemma3:1b"
    # configured but missing: still the best installed
    assert ModelManager(_cfg(tmp_path, fake_ollama.url, SPARKY_MODEL="phi4:14b")).default() == "qwen3.5:4b"


def test_cycle_and_smaller(tmp_path, fake_ollama):
    m = ModelManager(_cfg(tmp_path, fake_ollama.url))
    assert m.next_after("gemma3:1b") == "qwen3.5:4b"
    assert m.next_after("qwen3.5:4b") == "gemma3:1b"
    assert m.smaller_than("qwen3.5:4b") == ["gemma3:1b"]
    assert m.smaller_than("gemma3:1b") == []


def test_unreachable_server_means_no_models(tmp_path):
    m = ModelManager(_cfg(tmp_path, "http://127.0.0.1:9"))
    assert m.installed() == [] and m.default() == ""


def test_capabilities_from_server_then_catalog(tmp_path, fake_ollama):
    m = ModelManager(_cfg(tmp_path, fake_ollama.url))
    assert "tools" in m.capabilities("qwen3.5:4b")
    assert m.capabilities("gemma3:1b") == {"completion"}
    # unknown to the server: the catalog answers
    assert "tools" in m.capabilities("qwen3-coder:30b")


class FakeLocal:
    def __init__(self, fail=(), missing=(), conn=False, stream_then_fail=()):
        self.model = "?"
        self.fail, self.missing, self.conn = set(fail), set(missing), conn
        self.stream_then_fail = set(stream_then_fail)
        self.calls = []

    def set_model(self, m):
        self.model = m

    def abort(self):
        pass

    def chat_stream(self, messages, tools=None, system=None, on_text=None, on_think=None,
                    think=None, cancel=None):
        self.calls.append({"model": self.model, "tools": tools, "think": think})
        if self.conn:
            raise ProviderError("cannot reach the model server (refused)")
        if self.model in self.missing:
            raise ModelNotFound(self.model)
        if self.model in self.stream_then_fail:
            on_text("partial")
            raise ProviderError("died")
        if self.model in self.fail:
            raise ProviderError("model requires more system memory")
        on_text(self.model)
        return Reply(text=self.model, tool_calls=[], content_blocks=[text_block(self.model)])


def _router(tmp_path, fake_ollama, **kw):
    cfg = _cfg(tmp_path, fake_ollama.url)
    return Router(cfg, local=FakeLocal(**kw), manager=ModelManager(cfg, OllamaClient(fake_ollama.url)))


def test_router_serves_default_model(tmp_path, fake_ollama):
    r = _router(tmp_path, fake_ollama)
    reply, model = r.chat_stream([], on_text=lambda t: None)
    assert model == "qwen3.5:4b" and reply.text == "qwen3.5:4b"
    assert r.last_fallback is False


def test_router_falls_back_to_smaller_model_on_load_failure(tmp_path, fake_ollama):
    r = _router(tmp_path, fake_ollama, fail={"qwen3.5:4b"})
    reply, model = r.chat_stream([], on_text=lambda t: None)
    assert model == "gemma3:1b"
    assert r.last_fallback is True and r.fallback_from == "qwen3.5:4b"
    assert r.model == "qwen3.5:4b"      # the choice is kept for the next turn


def test_router_does_not_retry_after_text_streamed(tmp_path, fake_ollama):
    r = _router(tmp_path, fake_ollama, stream_then_fail={"qwen3.5:4b"})
    try:
        r.chat_stream([], on_text=lambda t: None)
        raise AssertionError("expected ProviderError")
    except ProviderError:
        pass
    assert [c["model"] for c in r.local.calls] == ["qwen3.5:4b"]


def test_router_missing_model_and_connection_errors_are_not_retried(tmp_path, fake_ollama):
    for kw in ({"missing": {"qwen3.5:4b"}}, {"conn": True}):
        r = _router(tmp_path, fake_ollama, **kw)
        try:
            r.chat_stream([], on_text=lambda t: None)
            raise AssertionError("expected an error")
        except ProviderError:
            pass
        assert len(r.local.calls) == 1


def test_router_offers_tools_and_think_only_when_supported(tmp_path, fake_ollama):
    r = _router(tmp_path, fake_ollama)
    tools = [{"name": "read_file"}]
    r.chat_stream([], tools=tools, on_text=lambda t: None)
    assert r.local.calls[-1]["tools"] == tools and r.local.calls[-1]["think"] is False
    r.think = True
    r.chat_stream([], tools=tools, on_text=lambda t: None)
    assert r.local.calls[-1]["think"] is True
    r.set_model("gemma3")
    r.chat_stream([], tools=tools, on_text=lambda t: None)
    assert r.local.calls[-1]["tools"] is None and r.local.calls[-1]["think"] is None


def test_router_set_model_and_cycle(tmp_path, fake_ollama):
    r = _router(tmp_path, fake_ollama)
    assert r.set_model("gem") == "gemma3:1b" and r.model == "gemma3:1b"
    assert r.set_model("nothing") is None and r.model == "gemma3:1b"
    assert r.cycle() == "qwen3.5:4b"
