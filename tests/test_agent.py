from pathlib import Path

from sparky import config
from sparky.agent import Agent
from sparky.providers.base import Reply, ToolCall, text_block


class ScriptedRouter:
    """Router stub that returns a queued sequence of replies."""
    def __init__(self, replies):
        self.replies = list(replies)
        self.last_fallback = False
        self.backend = "test"
    def chat(self, messages, tools=None, system=None):
        return self.replies.pop(0), "test"
    def chat_stream(self, messages, tools=None, system=None, on_text=None):
        reply = self.replies.pop(0)
        if on_text and reply.text:
            on_text(reply.text)        # simulate streaming the text
        return reply, "test"


def test_agent_runs_tool_then_returns_text(tmp_path):
    (tmp_path / "hi.txt").write_text("contents-here")
    cfg = config.load(root=tmp_path)
    # First reply: ask to read a file. Second reply: final text.
    replies = [
        Reply(
            text="reading",
            tool_calls=[ToolCall(id="t1", name="read_file", input={"path": "hi.txt"})],
            content_blocks=[text_block("reading"), {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "hi.txt"}}],
        ),
        Reply(text="the file says contents-here", tool_calls=[], content_blocks=[text_block("done")]),
    ]
    agent = Agent(cfg, ScriptedRouter(replies), cwd=tmp_path)

    events = []
    final = agent.run_turn("what's in hi.txt?", on_event=lambda k, d: events.append((k, d)))

    assert final == "the file says contents-here"
    kinds = [k for k, _ in events]
    assert "tool_start" in kinds and "tool_result" in kinds
    # the tool actually executed and saw the file
    tool_result = next(d for k, d in events if k == "tool_result")
    assert "contents-here" in tool_result["output"]


def test_agent_plain_answer_no_tools(tmp_path):
    cfg = config.load(root=tmp_path)
    replies = [Reply(text="just an answer", tool_calls=[], content_blocks=[text_block("just an answer")])]
    agent = Agent(cfg, ScriptedRouter(replies), cwd=tmp_path)
    assert agent.run_turn("hi") == "just an answer"
