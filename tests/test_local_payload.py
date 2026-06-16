from sparky import config
from sparky.providers.local import LocalProvider
from sparky.providers.base import text_block


def _provider(tmp_path):
    return LocalProvider(config.load(root=tmp_path))


def test_payload_translates_messages_and_tools(tmp_path):
    p = _provider(tmp_path)
    msgs = [{"role": "user", "content": [text_block("hello")]}]
    tools = [{"name": "list_dir", "description": "d", "input_schema": {"type": "object", "properties": {}}}]
    payload = p.build_payload(msgs, tools, "sys prompt")
    assert payload["model"] == config.DEFAULT_LOCAL_MODEL
    assert payload["stream"] is False
    assert payload["messages"][0] == {"role": "system", "content": "sys prompt"}
    assert payload["messages"][1] == {"role": "user", "content": "hello"}
    assert payload["tools"][0]["type"] == "function"
    assert payload["tools"][0]["function"]["name"] == "list_dir"


def test_tool_use_and_result_translation(tmp_path):
    p = _provider(tmp_path)
    msgs = [
        {"role": "user", "content": [text_block("read x")]},
        {"role": "assistant", "content": [
            {"type": "text", "text": "ok"},
            {"type": "tool_use", "id": "call_0", "name": "read_file", "input": {"path": "x"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "call_0", "content": "file body"},
        ]},
    ]
    payload = p.build_payload(msgs, None, None)
    roles = [m["role"] for m in payload["messages"]]
    assert roles == ["user", "assistant", "tool"]
    assert payload["messages"][1]["tool_calls"][0]["function"]["name"] == "read_file"
    assert payload["messages"][2]["content"] == "file body"


def test_image_block_dropped_with_note(tmp_path):
    p = _provider(tmp_path)
    img = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAA"}}
    msgs = [{"role": "user", "content": [img, text_block("what")]}]
    payload = p.build_payload(msgs, None, None)
    assert "image omitted" in payload["messages"][0]["content"]


def test_parse_tool_calls(tmp_path):
    body = {"message": {"role": "assistant", "content": "",
                        "tool_calls": [{"function": {"name": "list_dir", "arguments": {"path": "."}}}]}}
    reply = LocalProvider._parse(body)
    assert reply.wants_tools
    assert reply.tool_calls[0].name == "list_dir"
    assert reply.tool_calls[0].id == "call_0"
