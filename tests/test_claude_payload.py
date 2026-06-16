from sparky import config
from sparky.providers.claude import ClaudeProvider
from sparky.providers.base import text_block


def _provider(tmp_path):
    return ClaudeProvider(config.load(root=tmp_path))


def test_payload_basic(tmp_path):
    p = _provider(tmp_path)
    msgs = [{"role": "user", "content": [text_block("hi")]}]
    payload = p.build_payload(msgs, None, "be nice")
    assert payload["model"] == config.DEFAULT_MODEL
    assert payload["system"] == "be nice"
    assert payload["messages"] == msgs
    assert "tools" not in payload
    assert payload["max_tokens"] > 0


def test_payload_with_tools_and_image(tmp_path):
    p = _provider(tmp_path)
    img = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}
    msgs = [{"role": "user", "content": [img, text_block("what's this?")]}]
    tools = [{"name": "read_file", "description": "d", "input_schema": {"type": "object", "properties": {}}}]
    payload = p.build_payload(msgs, tools, None)
    assert payload["tools"][0]["name"] == "read_file"
    assert payload["messages"][0]["content"][0]["type"] == "image"
    assert "system" not in payload


def test_parse_text_and_tool_use(tmp_path):
    body = {
        "content": [
            {"type": "text", "text": "let me read it"},
            {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "x.py"}},
        ],
        "stop_reason": "tool_use",
    }
    reply = ClaudeProvider._parse(body)
    assert reply.text == "let me read it"
    assert reply.wants_tools
    assert reply.tool_calls[0].name == "read_file"
    assert reply.tool_calls[0].input == {"path": "x.py"}
    # assistant content blocks preserved for history
    assert reply.content_blocks[1]["type"] == "tool_use"
