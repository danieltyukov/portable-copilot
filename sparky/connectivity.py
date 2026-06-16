"""Background connectivity monitor.

A daemon thread periodically checks whether api.anthropic.com is reachable and
flips an `online` flag. The router reads this flag to choose a backend; the UI
reads it to render the ● online / ● OFFLINE marker.
"""

from __future__ import annotations

import socket
import threading
import time


def _reachable(host: str = "api.anthropic.com", port: int = 443, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class Monitor:
    def __init__(self, interval: float = 8.0):
        self.interval = interval
        self._online = _reachable()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def online(self) -> bool:
        return self._online

    def refresh(self) -> bool:
        self._online = _reachable()
        return self._online

    def start(self) -> "Monitor":
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            self._online = _reachable()
