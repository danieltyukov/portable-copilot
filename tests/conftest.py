import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

# Make the repo root importable so `import sparky` works without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # settings in the developer's environment must not leak into tests
    for key in ("SPARKY_MODEL", "SPARKY_MODE", "SPARKY_CTX", "SPARKY_THINK", "SPARKY_YOLO",
                "SPARKY_FAST_MODEL", "SPARKY_MAX_MODEL", "SPARKY_TIER", "SPARKY_ROOT", "OLLAMA_HOST"):
        monkeypatch.delenv(key, raising=False)


class FakeOllama:
    """A tiny stand-in for the Ollama HTTP API, enough to test the client,
    the chat provider and the model manager over real sockets."""

    def __init__(self):
        self.models = [
            {"name": "qwen3.5:4b", "size": 3_400_000_000, "details": {"family": "qwen35", "parameter_size": "4.7B"}},
            {"name": "gemma3:1b", "size": 815_000_000, "details": {"family": "gemma3", "parameter_size": "1B"}},
            {"name": "nomic-embed-text:latest", "size": 274_000_000,
             "details": {"family": "nomic-bert", "families": ["nomic-bert"]}},
        ]
        self.capabilities = {"qwen3.5:4b": ["completion", "tools", "vision", "thinking"],
                             "gemma3:1b": ["completion"]}
        self.chat_chunks: list[dict] = []     # NDJSON lines /api/chat streams back
        self.chat_status = 200
        self.chat_error = ""
        self.requests: list[tuple[str, dict]] = []
        self.pull_events: list[dict] = []
        self.hold = threading.Event()         # when cleared, chat streams stall after the first chunk
        self.hold.set()
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/version":
                    return self._json(200, {"version": "0.35.1"})
                if self.path == "/api/tags":
                    return self._json(200, {"models": fake.models})
                if self.path == "/api/ps":
                    return self._json(200, {"models": []})
                self._json(404, {"error": "not found"})

            def do_DELETE(self):
                body = self._read()
                fake.requests.append((self.path, body))
                fake.models = [m for m in fake.models if m["name"] != body.get("model")]
                self._json(200, {})

            def _read(self):
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n) or b"{}")

            def do_POST(self):
                body = self._read()
                fake.requests.append((self.path, body))
                if self.path == "/api/show":
                    name = body.get("model")
                    if name not in fake.capabilities:
                        return self._json(404, {"error": f"model '{name}' not found"})
                    return self._json(200, {"capabilities": fake.capabilities[name]})
                if self.path == "/api/pull":
                    self.send_response(200)
                    self.end_headers()
                    for ev in fake.pull_events:
                        self.wfile.write((json.dumps(ev) + "\n").encode())
                    return
                if self.path == "/api/chat":
                    if fake.chat_status != 200:
                        return self._json(fake.chat_status, {"error": fake.chat_error})
                    self.send_response(200)
                    self.send_header("Content-Type", "application/x-ndjson")
                    self.end_headers()
                    for i, chunk in enumerate(fake.chat_chunks):
                        self.wfile.write((json.dumps(chunk) + "\n").encode())
                        self.wfile.flush()
                        if i == 0 and not fake.hold.is_set():
                            fake.hold.wait(5)
                    return
                self._json(404, {"error": "not found"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        # a cancelled stream makes the handler write to a closed socket; expected
        self.server.handle_error = lambda request, client_address: None
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05},
                         daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake_ollama():
    f = FakeOllama()
    yield f
    f.close()
