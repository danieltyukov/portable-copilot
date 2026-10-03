"""A small client for the bundled Ollama server: list, inspect, download and
remove models. Chat requests live in providers/local.py.

Stdlib HTTP only, so the same code runs from the stick on every OS.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable, Iterator


class OllamaError(Exception):
    """The server is unreachable or refused a request."""


class OllamaClient:
    def __init__(self, host: str, timeout: float = 10.0):
        if not host.startswith(("http://", "https://")):
            host = "http://" + host
        self.host = host.rstrip("/")
        self.timeout = timeout
        self._show_cache: dict[str, dict] = {}

    # ---- plumbing ------------------------------------------------------------
    def _request(self, path: str, body: dict | None = None, method: str | None = None,
                 timeout: float | None = None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            f"{self.host}{path}", data=data, method=method or ("POST" if data else "GET"),
            headers={"content-type": "application/json"})
        try:
            return urllib.request.urlopen(req, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            try:
                detail = json.loads(detail).get("error", detail)
            except (json.JSONDecodeError, AttributeError):
                pass
            raise OllamaError(str(detail)[:300]) from e
        except (urllib.error.URLError, OSError) as e:
            raise OllamaError(f"cannot reach the model server at {self.host} ({e})") from e

    def _json(self, path: str, body: dict | None = None, method: str | None = None) -> dict:
        with self._request(path, body, method) as resp:
            raw = resp.read()
        return json.loads(raw) if raw else {}

    # ---- queries -----------------------------------------------------------------
    def reachable(self, timeout: float = 2.0) -> bool:
        try:
            with self._request("/api/version", timeout=timeout):
                return True
        except OllamaError:
            return False

    def version(self) -> str:
        return self._json("/api/version").get("version", "?")

    def models(self) -> list[dict]:
        """Installed models: [{name, size, details:{family, parameter_size, ...}}]."""
        return self._json("/api/tags").get("models", [])

    def show(self, name: str) -> dict:
        """Model details, including `capabilities` (completion, tools, vision,
        thinking, embedding) on current servers. Cached per name."""
        if name not in self._show_cache:
            self._show_cache[name] = self._json("/api/show", {"model": name})
        return self._show_cache[name]

    def capabilities(self, name: str) -> set[str]:
        try:
            return set(self.show(name).get("capabilities") or [])
        except OllamaError:
            return set()

    def running(self) -> list[dict]:
        return self._json("/api/ps").get("models", [])

    # ---- changes -----------------------------------------------------------------
    def delete(self, name: str) -> None:
        self._json("/api/delete", {"model": name}, method="DELETE")
        self._show_cache.pop(name, None)

    def pull(self, name: str, on_progress: Callable[[dict], None] | None = None) -> None:
        """Download a model, calling on_progress with each status event:
        {status, digest?, total?, completed?}. Raises OllamaError on failure."""
        for event in self._pull_events(name):
            if event.get("error"):
                raise OllamaError(event["error"])
            if on_progress:
                on_progress(event)

    def _pull_events(self, name: str) -> Iterator[dict]:
        # Pulls run for minutes; the timeout applies per read, not to the whole
        # download, so a generous one only bites when the connection stalls.
        with self._request("/api/pull", {"model": name, "stream": True}, timeout=300) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue


class PullProgress:
    """Turns pull events into one line of text: "downloading 41% of 2.6 GB".
    Ollama reports each layer separately, so sum them by digest."""

    def __init__(self):
        self.layers: dict[str, tuple[int, int]] = {}
        self.status = ""

    def update(self, event: dict) -> str:
        self.status = event.get("status", self.status)
        digest = event.get("digest")
        if digest and event.get("total"):
            self.layers[digest] = (int(event.get("completed") or 0), int(event["total"]))
        done = sum(c for c, _ in self.layers.values())
        total = sum(t for _, t in self.layers.values())
        if total and self.status.startswith("pulling"):
            return f"downloading {done * 100 // total:3d}% of {total / 1e9:.1f} GB"
        return self.status
