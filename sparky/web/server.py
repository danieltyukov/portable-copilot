"""The browser chat: `sparky.cmd web`.

A small stdlib HTTP server on 127.0.0.1 serves one page (sparky/web/static)
and a JSON API the page talks to; replies stream as server-sent events. It is
for one person on this computer, so it guards against other pages and
programs rather than other users:

  * it listens on 127.0.0.1 only;
  * the page needs the token from the link printed at start (it is then
    kept in an HttpOnly cookie), so another program or user on the computer
    cannot open it;
  * every API call must carry that token in a header, which only the page
    knows, so another website open in the browser cannot drive it;
  * the Host header must name 127.0.0.1 or localhost, which defeats DNS
    rebinding.

Risky tool actions still need approval, which the page asks for.
"""

from __future__ import annotations

import json
import queue
import secrets
import sys
import threading
import urllib.parse
import webbrowser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import __version__, catalog, engine, hardware, modes
from .. import sessions as sessions_mod
from ..context import list_files
from ..ollama import OllamaError, PullProgress
from ..providers.base import Cancelled, ModelNotFound, ProviderError

STATIC = Path(__file__).resolve().parent / "static"
FILES = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "theme-init.js": "text/javascript; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
    "icon.svg": "image/svg+xml",
}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
COOKIE = "sparky_token"
LOCKED = ("<!doctype html><meta charset=utf-8><title>Sparky</title>"
          "<p style='font:16px system-ui;margin:3rem'>Open Sparky with the link printed in the "
          "terminal where you ran <code>sparky.cmd web</code>.</p>")
MAX_BODY = 40 * 1024 * 1024        # a few photos, base64-encoded
CONFIRM_TIMEOUT = 600              # seconds an approval card waits before counting as "no"
DONE = object()


class WebApp:
    """The state behind the page: one conversation, one reply at a time."""

    def __init__(self, cfg, agent=None):
        self.cfg = cfg
        self.agent = agent or engine.build(cfg)
        self.token = secrets.token_urlsafe(24)
        self.session_id = sessions_mod.new_id()
        self.busy = threading.Lock()
        self.confirms: dict[str, dict] = {}

    # ---- state ------------------------------------------------------------------
    def state(self) -> dict:
        router = self.agent.router
        models = []
        for m in router.manager.installed():
            e = catalog.find(m.name)
            models.append({"name": m.name, "size_gb": round(m.size_gb, 1), "label": m.label,
                           "vision": "vision" in router.manager.capabilities(m.name),
                           "tools": "tools" in router.manager.capabilities(m.name),
                           "speed": e.speed if e else "", "note": e.note if e else ""})
        return {
            "version": __version__,
            "model": router.model,
            "models": models,
            "mode": self.agent.mode,
            "modes": [{"id": m.id, "label": m.label, "blurb": m.blurb} for m in modes.MODES.values()],
            "think": bool(router.think),
            "think_supported": bool(router.model) and router.supports("thinking"),
            "yolo": bool(self.cfg.yolo),
            "history": simple_history(self.agent.history),
            "busy": self.busy.locked(),
        }

    # ---- a turn -----------------------------------------------------------------
    def start_turn(self, text: str, images: list[dict]) -> queue.Queue | None:
        """Run a turn in the background; its events arrive on the returned
        queue, ending with DONE. None if a reply is already running."""
        if not self.busy.acquire(blocking=False):
            return None
        events: queue.Queue = queue.Queue()

        def on_event(kind, data):
            if kind == "thinking":
                events.put({"type": "thinking", "model": self.agent.router.model})
            elif kind == "assistant_delta":
                events.put({"type": "delta", "text": data["text"]})
            elif kind == "think_delta":
                if self.agent.router.think:
                    events.put({"type": "think_delta", "text": data["text"]})
            elif kind == "tool_start":
                events.put({"type": "tool_start", "name": data["name"], "input": data.get("input")})
            elif kind == "tool_result":
                out = str(data.get("output", ""))
                events.put({"type": "tool_result", "name": data["name"],
                            "output": out if len(out) < 8000 else out[:8000] + "\n[...cut]"})
            elif kind == "notice":
                events.put({"type": "notice", "text": data["text"]})
            elif kind == "stats":
                events.put({"type": "stats", "model": data.get("model"), "tokens": data.get("tokens"),
                            "tps": data.get("tps")})
            elif kind == "confirm":
                data["holder"]["approved"] = self._ask(events, data["command"])

        def work():
            try:
                final = self.agent.run_turn(text, images=images, on_event=on_event)
                sessions_mod.save(self.cfg, self.session_id, self.agent.history)
                events.put({"type": "done", "text": final})
            except Cancelled:
                events.put({"type": "done", "text": "", "stopped": True})
            except ModelNotFound:
                names = ", ".join(self.agent.router.manager.names()) or "none"
                events.put({"type": "error", "message": f"{self.agent.router.model} is not on this stick. "
                                                        f"Installed: {names}."})
            except ProviderError as e:
                events.put({"type": "error", "message": str(e)})
            except Exception as e:   # the page must always hear how a turn ended
                events.put({"type": "error", "message": f"error: {e}"})
            finally:
                self._release_confirms()
                self.busy.release()
                events.put(DONE)

        threading.Thread(target=work, daemon=True).start()
        return events

    # ---- slash commands the page does not handle itself ------------------------
    def start_command(self, text: str) -> queue.Queue | None:
        """Run a typed command (/pull, /context, ...) like a turn: notices on
        the queue, then done. The model never sees the command."""
        if not self.busy.acquire(blocking=False):
            return None
        events: queue.Queue = queue.Queue()

        def work():
            try:
                self._command(text, lambda msg: events.put({"type": "notice", "text": msg}))
                events.put({"type": "done", "text": ""})
            except Exception as e:   # the page must always hear how it ended
                events.put({"type": "error", "message": f"error: {e}"})
            finally:
                self.busy.release()
                events.put(DONE)

        threading.Thread(target=work, daemon=True).start()
        return events

    def _command(self, text: str, say) -> None:
        cmd, _, rest = text.strip().partition(" ")
        cmd, rest = cmd.lower(), rest.strip()
        if cmd == "/pull":
            self._pull(rest, say)
        elif cmd == "/context":
            files = list_files(self.cfg.context_dir)
            if not files:
                say(f"The context folder is empty. Put files in {self.cfg.context_dir} and every "
                    "conversation will know about them.")
            else:
                names = ", ".join(str(f.relative_to(self.cfg.context_dir)) for f in files[:30])
                more = f" and {len(files) - 30} more" if len(files) > 30 else ""
                say(f"{len(files)} file(s) in {self.cfg.context_dir}: {names}{more}.")
        elif cmd == "/sessions":
            items = sessions_mod.list_sessions(self.cfg)[:10]
            say("Saved conversations: " + "; ".join(d.get("title", "(untitled)") for d in items)
                if items else "No saved conversations yet.")
        elif cmd == "/resume":
            d = sessions_mod.latest(self.cfg)
            if not d:
                say("There is no saved conversation to resume.")
            else:
                self.agent.history = d.get("history", [])
                self.session_id = d.get("id", self.session_id)
                say(f"Resumed: {d.get('title', '(untitled)')}.")
        elif cmd == "/yolo":
            self.cfg.yolo = not self.cfg.yolo
            say("Shell commands now run without asking." if self.cfg.yolo
                else "Shell commands will ask first again.")
        else:
            say(f"Sparky does not know {cmd}. Type /help for the commands.")

    def _pull(self, name: str, say) -> None:
        if not name:
            say("Usage: /pull <name>, for example /pull qwen3.5:4b, /pull code, or /pull hf.co/<user>/<repo>.")
            return
        manager = self.agent.router.manager
        if name in catalog.PURPOSES:
            picks = catalog.recommend(name, hardware.total_ram_gb(), hardware.free_gb(self.cfg.root))
            if not picks:
                say(f"Nothing in the catalog for {name} fits this computer and stick.")
                return
            name = picks[0].tag
        say(f"Downloading {name}. This needs the internet and can take a while.")
        progress = PullProgress()
        last = {"quarter": -1}

        def show(ev):
            # one note per quarter of the download, not one per chunk
            line = progress.update(ev)
            if line.startswith("downloading"):
                quarter = int(line.split()[1].rstrip("%")) // 25
                if quarter != last["quarter"]:
                    last["quarter"] = quarter
                    say(line)

        try:
            manager.client.pull(name, show)
        except OllamaError as e:
            msg = str(e)
            if "newer version" in msg:
                msg = "it needs a newer model server than this stick has; run setup again to update it"
            elif "file does not exist" in msg or "not found" in msg:
                msg = "there is no model by that name; check it at https://ollama.com/library"
            say(f"Could not add {name}: {msg}.")
            return
        manager.installed(refresh=True)
        self.agent.router.set_model(name)
        say(f"{name} is ready and selected.")

    def _ask(self, events: queue.Queue, command: str) -> bool:
        cid = secrets.token_hex(6)
        slot = {"event": threading.Event(), "approved": False}
        self.confirms[cid] = slot
        events.put({"type": "confirm", "id": cid, "command": command})
        slot["event"].wait(CONFIRM_TIMEOUT)
        self.confirms.pop(cid, None)
        return bool(slot["approved"])

    def answer(self, cid: str, approved: bool) -> bool:
        slot = self.confirms.get(cid)
        if not slot:
            return False
        slot["approved"] = approved
        slot["event"].set()
        return True

    def _release_confirms(self) -> None:
        for slot in list(self.confirms.values()):
            slot["event"].set()

    def stop(self) -> None:
        self.agent.stop()
        self._release_confirms()


def simple_history(history: list[dict]) -> list[dict]:
    """The conversation as the page shows it: typed questions and answers,
    without tool traffic."""
    out = []
    for m in history:
        c = m.get("content")
        if isinstance(c, str):
            text, imgs = c, 0
        else:
            text = "".join(b.get("text", "") for b in c or [] if b.get("type") == "text")
            imgs = sum(1 for b in c or [] if b.get("type") == "image")
        if text.strip() or imgs:
            out.append({"role": m.get("role"), "text": text, "images": imgs})
    return out


def make_handler(app: WebApp, port_ref: dict):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Sparky"
        sys_version = ""

        def log_message(self, *args):   # keep the terminal quiet
            pass

        # ---- guards --------------------------------------------------------------
        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").lower()
            port = port_ref["port"]
            return host in (f"127.0.0.1:{port}", f"localhost:{port}")

        def _token_ok(self) -> bool:
            return secrets.compare_digest(self.headers.get("X-Sparky-Token") or "", app.token)

        def _cookie_ok(self) -> bool:
            jar = SimpleCookie()
            try:
                jar.load(self.headers.get("Cookie") or "")
            except Exception:
                return False
            got = jar.get(COOKIE)
            return bool(got) and secrets.compare_digest(got.value, app.token)

        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise ValueError("request too large")
            raw = self.rfile.read(n) if n else b"{}"
            data = json.loads(raw or b"{}")
            if not isinstance(data, dict):
                raise ValueError("expected a JSON object")
            return data

        # ---- routes --------------------------------------------------------------
        def do_GET(self):
            if not self._host_ok():
                return self._json(403, {"error": "bad host"})
            path, _, query = self.path.partition("?")
            if path in ("/", "/index.html"):
                # The page is only for whoever has the link printed in the
                # terminal: the link's token is swapped for an HttpOnly cookie
                # and stripped from the address bar. Without either, another
                # program or user on this computer gets nothing.
                given = urllib.parse.parse_qs(query).get("token", [""])[0]
                if given and secrets.compare_digest(given, app.token):
                    return self._send(303, b"", "text/plain", {
                        "Location": "/", "Referrer-Policy": "no-referrer",
                        "Set-Cookie": f"{COOKIE}={app.token}; HttpOnly; SameSite=Strict; Path=/"})
                if not self._cookie_ok():
                    return self._send(403, LOCKED.encode("utf-8"), "text/html; charset=utf-8")
                html = (STATIC / "index.html").read_text(encoding="utf-8").replace("{{TOKEN}}", app.token)
                return self._send(200, html.encode("utf-8"), FILES["index.html"],
                                  {"Content-Security-Policy": CSP, "Referrer-Policy": "no-referrer"})
            if path.startswith("/static/"):
                name = path[len("/static/"):]
                if name in FILES and name != "index.html" and (STATIC / name).is_file():
                    return self._send(200, (STATIC / name).read_bytes(), FILES[name])
                return self._json(404, {"error": "not found"})
            if path == "/favicon.ico":
                return self._send(200, (STATIC / "icon.svg").read_bytes(), FILES["icon.svg"]) \
                    if (STATIC / "icon.svg").is_file() else self._json(404, {"error": "not found"})
            if path == "/api/state":
                if not self._token_ok():
                    return self._json(403, {"error": "bad token"})
                return self._json(200, app.state())
            return self._json(404, {"error": "not found"})

        def do_POST(self):
            if not self._host_ok():
                return self._json(403, {"error": "bad host"})
            if not self._token_ok():
                return self._json(403, {"error": "bad token"})
            try:
                body = self._body()
            except (ValueError, json.JSONDecodeError) as e:
                return self._json(400, {"error": str(e)})
            path = self.path.split("?", 1)[0]
            router = app.agent.router

            if path == "/api/chat":
                return self._chat(body)
            if path == "/api/stop":
                app.stop()
                return self._json(200, {"ok": True})
            if path == "/api/confirm":
                ok = app.answer(str(body.get("id", "")), bool(body.get("approved")))
                return self._json(200 if ok else 404, {"ok": ok})
            if path == "/api/model":
                if app.busy.locked():
                    return self._json(409, {"error": "busy"})
                router.manager.installed(refresh=True)
                if not router.set_model(str(body.get("name", ""))):
                    return self._json(404, {"error": f"no installed model matches {body.get('name')!r}"})
                return self._json(200, app.state())
            if path == "/api/mode":
                hit = modes.resolve(str(body.get("id", "")))
                if not hit:
                    return self._json(404, {"error": "unknown mode"})
                app.agent.mode = hit
                return self._json(200, app.state())
            if path == "/api/think":
                router.think = bool(body.get("on"))
                return self._json(200, app.state())
            if path == "/api/clear":
                if app.busy.locked():
                    return self._json(409, {"error": "busy"})
                app.agent.history.clear()
                app.session_id = sessions_mod.new_id()
                return self._json(200, app.state())
            return self._json(404, {"error": "not found"})

        def _chat(self, body: dict):
            text = str(body.get("text", "")).strip()
            images = []
            for img in body.get("images") or []:
                if isinstance(img, dict) and img.get("data"):
                    images.append({"type": "image", "source": {
                        "type": "base64", "media_type": str(img.get("media_type") or "image/png"),
                        "data": str(img["data"])}})
            if not text and not images:
                return self._json(400, {"error": "empty message"})
            if text.startswith("/") and not images:
                events = app.start_command(text)
            elif not app.agent.router.model:
                return self._json(400, {"error": engine.no_models_message(app.cfg)})
            else:
                events = app.start_turn(text or "What is in this image?", images)
            if events is None:
                return self._json(409, {"error": "busy"})
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            while True:
                ev = events.get()
                if ev is DONE:
                    break
                try:
                    self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    app.stop()      # the tab was closed: stop generating
                    break
            self.close_connection = True

    return Handler


def serve_web(cfg, port: int = 0, open_browser: bool = True) -> int:
    app = WebApp(cfg)
    port_ref = {"port": port}
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app, port_ref))
    server.daemon_threads = True
    port_ref["port"] = server.server_address[1]
    url = f"http://127.0.0.1:{port_ref['port']}/?token={app.token}"
    print("Sparky is open in your browser. If it did not open, use this link:")
    print(f"  {url}")
    print("The link only works on this computer, and only until Sparky stops. Press Ctrl-C here to stop.")
    if not app.agent.router.model:
        print("\n" + engine.no_models_message(cfg), file=sys.stderr)
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        app.stop()
        server.server_close()
    return 0
