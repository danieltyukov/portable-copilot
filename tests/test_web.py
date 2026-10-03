import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from sparky import config
from sparky.agent import Agent
from sparky.models import ModelManager
from sparky.ollama import OllamaClient
from sparky.providers.base import Reply, ToolCall, text_block
from sparky.web.server import WebApp, make_handler, simple_history


class Router:
    def __init__(self, manager, replies):
        self.manager = manager
        self.model = manager.default()
        self.think = False
        self.replies = list(replies)
        self.last_fallback = False
        self.fallback_from = ""
        self.release = threading.Event()
        self.release.set()

    def set_model(self, name):
        hit = self.manager.resolve(name)
        if hit:
            self.model = hit
        return hit

    def supports(self, cap, model=None):
        return cap in self.manager.capabilities(model or self.model)

    def chat_stream(self, messages, tools=None, system=None, on_text=None, on_think=None, cancel=None):
        reply = self.replies.pop(0)
        on_text(reply.text or "")
        self.release.wait(5)
        if cancel is not None and cancel.is_set():
            from sparky.providers.base import Cancelled
            raise Cancelled()
        return reply, self.model

    def abort(self):
        self.release.set()


@pytest.fixture
def web(tmp_path, fake_ollama):
    cfg = config.load(root=tmp_path)
    cfg.ollama_host = fake_ollama.url
    cfg.mode = "code"
    manager = ModelManager(cfg, OllamaClient(fake_ollama.url))
    router = Router(manager, [])
    agent = Agent(cfg, router, cwd=tmp_path)
    app = WebApp(cfg, agent=agent)
    port_ref = {"port": 0}
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app, port_ref))
    server.daemon_threads = True
    port_ref["port"] = server.server_address[1]
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    base = f"http://127.0.0.1:{port_ref['port']}"
    yield app, router, base
    server.shutdown()
    server.server_close()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def call(base, path, body=None, token=None, host=None, cookie=None):
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    if token:
        headers["X-Sparky-Token"] = token
    if host:
        headers["Host"] = host
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=10) as r:
            return r.status, r.read().decode(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), e.headers


def events_of(text):
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def test_page_needs_the_link_token_then_a_cookie(web):
    app, _, base = web
    code, html, _ = call(base, "/")
    assert code == 403 and app.token not in html
    assert call(base, "/?token=wrong")[0] == 403
    code, _, headers = call(base, f"/?token={app.token}")
    assert code == 303 and headers["Location"] == "/"
    cookie = headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    code, html, headers = call(base, "/", cookie=cookie.split(";")[0])
    assert code == 200 and app.token in html and "{{TOKEN}}" not in html
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert call(base, "/static/app.js")[0] == 200
    assert call(base, "/static/../server.py")[0] == 404


def test_api_needs_the_token_and_a_local_host(web):
    app, _, base = web
    assert call(base, "/api/state")[0] == 403
    assert call(base, "/api/state", token="wrong")[0] == 403
    assert call(base, "/api/state", token=app.token, host="evil.example:80")[0] == 403
    code, body, _ = call(base, "/api/state", token=app.token)
    state = json.loads(body)
    assert code == 200 and state["model"] == "qwen3.5:4b"
    assert [m["name"] for m in state["models"]] == ["gemma3:1b", "qwen3.5:4b"]
    assert {m["id"] for m in state["modes"]} == {"chat", "code", "write", "study"}


def test_switching_model_mode_and_think(web):
    app, router, base = web
    s = json.loads(call(base, "/api/model", {"name": "gemma"}, app.token)[1])
    assert s["model"] == "gemma3:1b" and s["think_supported"] is False
    assert call(base, "/api/model", {"name": "zzz"}, app.token)[0] == 404
    assert json.loads(call(base, "/api/mode", {"id": "write"}, app.token)[1])["mode"] == "write"
    assert json.loads(call(base, "/api/think", {"on": True}, app.token)[1])["think"] is True


def test_chat_streams_events_and_saves_history(web):
    app, router, base = web
    router.replies = [Reply(text="Hello!", tool_calls=[], content_blocks=[text_block("Hello!")],
                            stats={"tokens": 3, "tps": 12.5})]
    code, body, headers = call(base, "/api/chat", {"text": "hi"}, app.token)
    assert code == 200 and headers["Content-Type"].startswith("text/event-stream")
    evs = events_of(body)
    assert [e["type"] for e in evs] == ["thinking", "delta", "stats", "done"]
    assert evs[-1]["text"] == "Hello!"
    hist = json.loads(call(base, "/api/state", token=app.token)[1])["history"]
    assert [h["role"] for h in hist] == ["user", "assistant"]
    assert list((app.cfg.sessions_dir).glob("*.json"))


def test_shell_approval_round_trip(web, tmp_path):
    app, router, base = web
    router.replies = [
        Reply(text="", tool_calls=[ToolCall("c1", "run_shell", {"command": "echo approved-run"})],
              content_blocks=[{"type": "tool_use", "id": "c1", "name": "run_shell",
                               "input": {"command": "echo approved-run"}}]),
        Reply(text="done", tool_calls=[], content_blocks=[text_block("done")]),
    ]

    def approve():
        for _ in range(100):
            if app.confirms:
                cid = next(iter(app.confirms))
                call(base, "/api/confirm", {"id": cid, "approved": True}, app.token)
                return
            threading.Event().wait(0.05)

    threading.Thread(target=approve, daemon=True).start()
    evs = events_of(call(base, "/api/chat", {"text": "run it"}, app.token)[1])
    kinds = [e["type"] for e in evs]
    assert "confirm" in kinds and kinds[-1] == "done"
    result = next(e for e in evs if e["type"] == "tool_result")
    assert "approved-run" in result["output"]


def test_stop_ends_the_stream_and_busy_is_reported(web):
    app, router, base = web
    router.replies = [Reply(text="slow", tool_calls=[], content_blocks=[text_block("slow")])]
    router.release.clear()
    out = {}
    t = threading.Thread(target=lambda: out.update(r=call(base, "/api/chat", {"text": "x"}, app.token)))
    t.start()
    for _ in range(100):
        if app.busy.locked():
            break
        threading.Event().wait(0.02)
    assert call(base, "/api/chat", {"text": "again"}, app.token)[0] == 409
    call(base, "/api/stop", {}, app.token)
    t.join(5)
    evs = events_of(out["r"][1])
    assert evs[-1] == {"type": "done", "text": "", "stopped": True}
    assert app.agent.history == []


def test_empty_message_is_rejected(web):
    app, _, base = web
    assert call(base, "/api/chat", {"text": "  "}, app.token)[0] == 400


def test_simple_history_hides_tool_traffic():
    h = [{"role": "user", "content": [text_block("q")]},
         {"role": "assistant", "content": [{"type": "tool_use", "id": "1", "name": "x", "input": {}}]},
         {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "1", "content": "r"}]},
         {"role": "assistant", "content": [text_block("a")]}]
    assert simple_history(h) == [{"role": "user", "text": "q", "images": 0},
                                 {"role": "assistant", "text": "a", "images": 0}]
