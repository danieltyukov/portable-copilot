import threading

import pytest

from sparky import config
from sparky.providers.base import Cancelled, ModelNotFound, ProviderError, text_block
from sparky.providers.local import LocalProvider, extract_text_tool_calls


def _provider(tmp_path, url="http://127.0.0.1:9", model="qwen3.5:4b"):
    cfg = config.load(root=tmp_path)
    cfg.ollama_host = url
    return LocalProvider(cfg, model=model, ctx=8192)


def test_payload_translates_messages_tools_and_options(tmp_path):
    p = _provider(tmp_path)
    msgs = [{"role": "user", "content": [text_block("hello")]}]
    tools = [{"name": "list_dir", "description": "d", "input_schema": {"type": "object", "properties": {}}}]
    payload = p.build_payload(msgs, tools, "sys prompt", think=False)
    assert payload["model"] == "qwen3.5:4b"
    assert payload["options"]["num_ctx"] == 8192     # never Ollama's small default
    assert payload["think"] is False
    assert payload["messages"][0] == {"role": "system", "content": "sys prompt"}
    assert payload["messages"][1] == {"role": "user", "content": "hello"}
    assert payload["tools"][0]["function"]["name"] == "list_dir"
    assert "think" not in p.build_payload(msgs, None, None)


def test_tool_use_and_result_translation(tmp_path):
    p = _provider(tmp_path)
    msgs = [
        {"role": "user", "content": [text_block("read x")]},
        {"role": "assistant", "content": [
            {"type": "text", "text": "ok"},
            {"type": "tool_use", "id": "call_0", "name": "read_file", "input": {"path": "x"}},
        ]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_0", "content": "file body"}]},
    ]
    payload = p.build_payload(msgs, None, None)
    assert [m["role"] for m in payload["messages"]] == ["user", "assistant", "tool"]
    assert payload["messages"][1]["tool_calls"][0]["function"]["name"] == "read_file"
    assert payload["messages"][2]["content"] == "file body"


def test_images_go_in_the_images_field(tmp_path):
    p = _provider(tmp_path)
    img = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAA"}}
    payload = p.build_payload([{"role": "user", "content": [img, text_block("what")]}], None, None)
    assert payload["messages"][0]["images"] == ["AAA"]
    assert payload["messages"][0]["content"] == "what"


def test_stream_collects_text_thinking_and_stats(tmp_path, fake_ollama):
    fake_ollama.chat_chunks = [
        {"message": {"thinking": "let me see"}},
        {"message": {"content": "Hello"}},
        {"message": {"content": " there"}},
        {"done": True, "done_reason": "stop", "eval_count": 20, "eval_duration": 2_000_000_000,
         "prompt_eval_count": 50},
    ]
    p = _provider(tmp_path, fake_ollama.url)
    texts, thoughts = [], []
    reply = p.chat_stream([{"role": "user", "content": "hi"}], on_text=texts.append, on_think=thoughts.append)
    assert reply.text == "Hello there" and texts == ["Hello", " there"]
    assert reply.thinking == "let me see" and thoughts == ["let me see"]
    assert reply.stats == {"tokens": 20, "prompt_tokens": 50, "seconds": 2.0, "tps": 10.0}
    assert reply.stop_reason == "stop"
    sent = fake_ollama.requests[-1][1]
    assert sent["stream"] is True and sent["options"]["num_ctx"] == 8192


def test_stream_tool_calls(tmp_path, fake_ollama):
    fake_ollama.chat_chunks = [
        {"message": {"tool_calls": [{"function": {"name": "list_dir", "arguments": {"path": "."}}}]}},
        {"done": True},
    ]
    reply = _provider(tmp_path, fake_ollama.url).chat_stream([], tools=[{"name": "list_dir"}])
    assert reply.wants_tools and reply.tool_calls[0].input == {"path": "."}


def test_missing_model_is_its_own_error(tmp_path, fake_ollama):
    fake_ollama.chat_status, fake_ollama.chat_error = 404, "model 'x' not found"
    with pytest.raises(ModelNotFound):
        _provider(tmp_path, fake_ollama.url).chat_stream([])


def test_server_error_and_stream_error(tmp_path, fake_ollama):
    fake_ollama.chat_status, fake_ollama.chat_error = 500, "model requires more system memory"
    with pytest.raises(ProviderError, match="memory"):
        _provider(tmp_path, fake_ollama.url).chat_stream([])
    fake_ollama.chat_status = 200
    fake_ollama.chat_chunks = [{"error": "runner crashed"}]
    with pytest.raises(ProviderError, match="crashed"):
        _provider(tmp_path, fake_ollama.url).chat_stream([])


def test_unreachable_server(tmp_path):
    with pytest.raises(ProviderError, match="cannot reach"):
        _provider(tmp_path).chat_stream([])


def test_cancel_stops_a_stalled_stream(tmp_path, fake_ollama):
    fake_ollama.chat_chunks = [{"message": {"content": "a"}}, {"message": {"content": "b"}}, {"done": True}]
    fake_ollama.hold.clear()           # the server stalls after the first chunk
    p = _provider(tmp_path, fake_ollama.url)
    cancel = threading.Event()

    def stop_soon(_text):
        cancel.set()
        threading.Timer(0.1, p.abort).start()

    with pytest.raises(Cancelled):
        p.chat_stream([], on_text=stop_soon, cancel=cancel)
    fake_ollama.hold.set()


def test_text_tool_call_fallback():
    text = 'Let me list them.\n```json\n{"name": "list_dir", "arguments": {"path": "."}}\n```'
    calls, cleaned = extract_text_tool_calls(text, ["list_dir", "read_file"])
    assert len(calls) == 1 and calls[0].name == "list_dir" and calls[0].input == {"path": "."}
    assert "list_dir" not in cleaned
    assert extract_text_tool_calls('{"name": "unknown_tool", "arguments": {}}', ["list_dir"])[0] == []


def test_parse_uses_text_fallback():
    body = {"message": {"role": "assistant", "content": '{"name": "read_file", "arguments": {"path": "x.py"}}'}}
    reply = LocalProvider._parse(body, ["read_file"])
    assert reply.wants_tools and reply.tool_calls[0].name == "read_file"


def test_thinking_gets_a_bigger_reply_budget_and_tiny_replies_no_speed(tmp_path):
    from sparky.providers.local import MAX_PREDICT, stats_from
    p = _provider(tmp_path)
    plain = p.build_payload([], None, None, think=False)["options"]["num_predict"]
    thinking = p.build_payload([], None, None, think=True)["options"]["num_predict"]
    assert plain == MAX_PREDICT and thinking > plain
    assert stats_from({"eval_count": 1, "eval_duration": 1000}) == {}
