"""Normalized provider types for the local Ollama backend.

The normalized message/block schema uses Anthropic's block shape (text /
tool_use / tool_result) as a stable internal format; the Ollama adapter
translates to and from it. A `Reply` carries the assistant's content blocks
(text + tool_use) so the agent loop can append them to history verbatim.
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
    thinking: str = ""              # reasoning text, when the model thinks aloud
    stats: dict = field(default_factory=dict)   # tokens, seconds, tps

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


# A ToolSpec is a plain dict: {"name", "description", "input_schema"}.
ToolSpec = dict


class ProviderError(Exception):
    """A chat request failed (server down, HTTP error, bad response)."""


class ModelNotFound(ProviderError):
    """The requested model is not installed on this stick."""


class Cancelled(Exception):
    """The user stopped the reply. Not an error, so not a ProviderError."""


def text_block(text: str) -> dict:
    return {"type": "text", "text": text}
