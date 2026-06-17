"""Conversation persistence + resume (parity with OpenClaude's session resume).

Each session is one JSON file in data/sessions/. Image data is stripped on save
(replaced with a marker) so files stay small; resumed sessions keep the text.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


def _title(history: list[dict]) -> str:
    for m in history:
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            return c[:60]
        for b in c if isinstance(c, list) else []:
            if isinstance(b, dict) and b.get("type") == "text" and b.get("text"):
                return b["text"][:60]
    return "session"


def _strip_images(history: list[dict]) -> list[dict]:
    out = []
    for m in history:
        c = m.get("content")
        if isinstance(c, list):
            blocks = []
            for b in c:
                if isinstance(b, dict) and b.get("type") == "image":
                    blocks.append({"type": "text", "text": "[image from earlier in this session]"})
                else:
                    blocks.append(b)
            out.append({**m, "content": blocks})
        else:
            out.append(m)
    return out


def save(cfg, session_id: str, history: list[dict]) -> None:
    if not history:
        return
    cfg.sessions_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "id": session_id,
        "title": _title(history),
        "updated": time.time(),
        "history": _strip_images(history),
    }
    (cfg.sessions_dir / f"{session_id}.json").write_text(json.dumps(data), encoding="utf-8")


def list_sessions(cfg) -> list[dict]:
    if not cfg.sessions_dir.exists():
        return []
    files = sorted(cfg.sessions_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for p in files:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def latest(cfg) -> dict | None:
    items = list_sessions(cfg)
    return items[0] if items else None


def new_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.localtime())
