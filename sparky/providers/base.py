"""Normalized provider types shared by the Claude and Ollama backends.

The normalized message/block schema is intentionally Anthropic's own shape, so
the Claude path is a near-passthrough and only the Ollama adapter does
translation work. A `Reply` carries the assistant's content blocks (text +
tool_use) so the agent loop can append them to history verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class Reply:
    text: str                       # concatenated text blocks
    tool_calls: list[ToolCall]      # tool_use requests, if any
    content_blocks: list[dict]      # normalized assistant blocks (text + tool_use)
    stop_reason: str | None = None
    raw: Any = None

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


# A ToolSpec is a plain dict: {"name", "description", "input_schema"} — the exact
# shape the Anthropic Messages API expects, and easy to adapt for Ollama.
ToolSpec = dict


class ProviderError(Exception):
    """Raised when a provider call fails (network, HTTP, auth, parse)."""


def text_block(text: str) -> dict:
    return {"type": "text", "text": text}
