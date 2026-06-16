from sparky import config
from sparky.router import Router
from sparky.providers.base import ProviderError, Reply, text_block


class FakeMonitor:
    def __init__(self, online):
        self.online = online
    def refresh(self):
        return self.online


class FakeProvider:
    def __init__(self, label, raises=False):
        self.label = label
        self.raises = raises
        self.model = label
        self.calls = 0
    def chat(self, messages, tools=None, system=None):
        self.calls += 1
        if self.raises:
            raise ProviderError("boom")
        return Reply(text=self.label, tool_calls=[], content_blocks=[text_block(self.label)])


def _cfg(tmp_path, key="sk-x"):
    cfg = config.load(root=tmp_path)
    cfg.anthropic_api_key = key
    return cfg


def test_online_uses_claude(tmp_path):
    claude, local = FakeProvider("claude"), FakeProvider("local")
    r = Router(_cfg(tmp_path), monitor=FakeMonitor(True), claude=claude, local=local)
    reply, backend = r.chat([], system=None)
    assert reply.text == "claude"
    assert backend.startswith("claude")
    assert local.calls == 0


def test_claude_error_falls_back_to_local(tmp_path):
    claude, local = FakeProvider("claude", raises=True), FakeProvider("local")
    r = Router(_cfg(tmp_path), monitor=FakeMonitor(True), claude=claude, local=local)
    reply, backend = r.chat([], system=None)
    assert reply.text == "local"
    assert "fallback" in backend
    assert r.last_fallback is True


def test_offline_uses_local(tmp_path):
    claude, local = FakeProvider("claude"), FakeProvider("local")
    r = Router(_cfg(tmp_path), monitor=FakeMonitor(False), claude=claude, local=local)
    reply, backend = r.chat([], system=None)
    assert reply.text == "local"
    assert claude.calls == 0
    assert r.last_fallback is False  # planned offline, not a mid-call drop


def test_no_key_uses_local_even_if_online(tmp_path):
    claude, local = FakeProvider("claude"), FakeProvider("local")
    r = Router(_cfg(tmp_path, key=None), monitor=FakeMonitor(True), claude=claude, local=local)
    reply, _ = r.chat([], system=None)
    assert reply.text == "local"
    assert claude.calls == 0
