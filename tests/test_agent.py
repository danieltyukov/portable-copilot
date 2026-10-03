import pytest

from sparky import config
from sparky.agent import Agent, fit_history
from sparky.providers.base import Cancelled, ProviderError, Reply, ToolCall, text_block


class ScriptedRouter:
    """Router stub that returns a queued sequence of replies (or raises)."""
    def __init__(self, replies):
        self.replies = list(replies)
        self.last_fallback = False
        self.fallback_from = ""
        self.model = "test:1b"
        self.seen = []

    def chat_stream(self, messages, tools=None, system=None, on_text=None, on_think=None, cancel=None):
        self.seen.append({"messages": list(messages), "tools": tools, "system": system})
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        if on_text and reply.text:
            on_text(reply.text)
        return reply, self.model

    def abort(self):
        pass


def _tool_reply(name, args, cid="t1"):
    return Reply(text="", tool_calls=[ToolCall(id=cid, name=name, input=args)],
                 content_blocks=[{"type": "tool_use", "id": cid, "name": name, "input": args}])


def _text(t, stats=None):
    return Reply(text=t, tool_calls=[], content_blocks=[text_block(t)], stats=stats or {})


def _agent(tmp_path, replies, mode="code"):
    cfg = config.load(root=tmp_path)
    cfg.mode = mode
    return Agent(cfg, ScriptedRouter(replies), cwd=tmp_path)


def test_runs_a_tool_then_answers(tmp_path):
    (tmp_path / "hi.txt").write_text("contents-here")
    agent = _agent(tmp_path, [_tool_reply("read_file", {"path": "hi.txt"}),
                              _text("it says contents-here", {"tokens": 5, "tps": 9.0})])
    events = []
    final = agent.run_turn("what's in hi.txt?", on_event=lambda k, d: events.append((k, d)))
    assert final == "it says contents-here"
    kinds = [k for k, _ in events]
    assert kinds.index("tool_start") < kinds.index("tool_result") < kinds.index("stats")
    assert "contents-here" in next(d for k, d in events if k == "tool_result")["output"]


def test_modes_decide_the_tools(tmp_path):
    chat = _agent(tmp_path, [_text("hi")], mode="chat")
    chat.run_turn("hello")
    assert chat.router.seen[0]["tools"] is None
    study = _agent(tmp_path, [_text("hi")], mode="study")
    study.run_turn("hello")
    assert {t["name"] for t in study.router.seen[0]["tools"]} == {"read_file", "list_dir", "search"}


def test_a_tool_outside_the_mode_is_refused(tmp_path):
    agent = _agent(tmp_path, [_tool_reply("run_shell", {"command": "echo hi"}), _text("ok")], mode="study")
    events = []
    agent.run_turn("x", on_event=lambda k, d: events.append((k, d)))
    out = next(d for k, d in events if k == "tool_result")["output"]
    assert "not available in study mode" in out


def test_cancel_removes_the_unfinished_turn(tmp_path):
    agent = _agent(tmp_path, [_text("first"), Cancelled()])
    agent.run_turn("one")
    with pytest.raises(Cancelled):
        agent.run_turn("two")
    assert len(agent.history) == 2      # only the first exchange remains


def test_an_error_does_not_leave_a_dangling_question(tmp_path):
    agent = _agent(tmp_path, [ProviderError("down")])
    with pytest.raises(ProviderError):
        agent.run_turn("hello")
    assert agent.history == []


def test_fallback_notice(tmp_path):
    agent = _agent(tmp_path, [_text("ok")])
    agent.router.last_fallback = True
    agent.router.fallback_from = "big:30b"
    events = []
    agent.run_turn("x", on_event=lambda k, d: events.append((k, d)))
    assert any(k == "notice" and "big:30b" in d["text"] for k, d in events)


def test_context_folder_is_in_the_system_prompt(tmp_path):
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "notes.md").write_text("the launch is on Tuesday")
    agent = _agent(tmp_path, [_text("ok")], mode="chat")
    agent.run_turn("when is the launch?")
    assert "the launch is on Tuesday" in agent.router.seen[0]["system"]


def _q(t):
    return {"role": "user", "content": [text_block(t)]}


def _a(t):
    return {"role": "assistant", "content": [text_block(t)]}


def test_fit_history_keeps_everything_that_fits():
    h = [_q("a"), _a("b"), _q("c")]
    assert fit_history(h, 10_000) == h


def test_fit_history_drops_old_turns_first():
    h = [_q("x" * 500), _a("y" * 500), _q("recent"), _a("answer"), _q("now")]
    out = fit_history(h, 300)
    assert out[0] == _q("recent") or out[0] == _q("now")
    assert out[-1] == _q("now")


def test_fit_history_never_starts_with_a_tool_result():
    tool_use = {"role": "assistant", "content": [{"type": "tool_use", "id": "1", "name": "read_file", "input": {}}]}
    result = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "1", "content": "z" * 5000}]}
    h = [_q("old"), tool_use, result, _a("done"), _q("new")]
    out = fit_history(h, 200)
    assert out[0]["role"] == "user" and out[0]["content"][0]["type"] == "text"


def test_fit_history_shortens_old_tool_output():
    result = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "1", "content": "z" * 9000}]}
    h = [_q("old"), result, _a("done"), _q("new")]
    out = fit_history(h, 4000)
    assert len(out) == 4
    assert len(out[1]["content"][0]["content"]) < 2000
