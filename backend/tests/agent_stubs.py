"""Stand-ins for the Anthropic client, shared by the agent tests.

Nothing here touches the network: the stub records every request and replays a
scripted sequence of responses, so the orchestrator's loop, tool routing, retry
and token accounting can all be asserted exactly.
"""

from __future__ import annotations

import json
from typing import Any


class TextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class ToolUseBlock:
    type = "tool_use"

    def __init__(self, name: str, arguments: dict[str, Any], block_id: str = "tu_1") -> None:
        self.name = name
        self.input = arguments
        self.id = block_id


class Usage:
    def __init__(self, input_tokens: int = 100, output_tokens: int = 20) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class StubMessage:
    """Mimics anthropic.types.Message closely enough for the orchestrator."""

    def __init__(
        self,
        content: list[Any],
        *,
        stop_reason: str = "end_turn",
        input_tokens: int = 100,
        output_tokens: int = 20,
    ) -> None:
        self.content = content
        self.stop_reason = stop_reason
        self.usage = Usage(input_tokens, output_tokens)


def final(payload: dict[str, Any], **kwargs: Any) -> StubMessage:
    """A turn where Claude answers with schema-constrained JSON."""
    return StubMessage([TextBlock(json.dumps(payload))], **kwargs)


def tool_turn(*calls: tuple[str, dict[str, Any]], **kwargs: Any) -> StubMessage:
    """A turn where Claude requests one or more tool calls."""
    blocks = [
        ToolUseBlock(name, arguments, block_id=f"tu_{index}")
        for index, (name, arguments) in enumerate(calls)
    ]
    return StubMessage(blocks, stop_reason="tool_use", **kwargs)


class StubMessages:
    def __init__(self, owner: "StubAnthropic") -> None:
        self._owner = owner

    async def create(self, **kwargs: Any) -> StubMessage:
        self._owner.requests.append(kwargs)
        if not self._owner.script:
            raise AssertionError("StubAnthropic ran out of scripted responses")
        nxt = self._owner.script.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


class StubAnthropic:
    """Replays `script` in order; raises any BaseException it contains."""

    def __init__(self, *script: Any) -> None:
        self.script: list[Any] = list(script)
        self.requests: list[dict[str, Any]] = []
        self.messages = StubMessages(self)

    @property
    def call_count(self) -> int:
        return len(self.requests)

    @property
    def last_request(self) -> dict[str, Any]:
        assert self.requests, "no request was made"
        return self.requests[-1]


class FakeToolbox:
    """An McpToolbox stand-in that records calls and replays canned results."""

    def __init__(self, results: dict[str, Any] | None = None,
                 errors: dict[str, str] | None = None) -> None:
        self.results = results or {}
        self.errors = errors or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.tools = [
            {"name": name, "description": f"tool {name}", "input_schema": {"type": "object"}}
            for name in ("flag_prohibited", "match_wishlist", "create_listing_from_photo",
                         "draft_coordination", "classify_item")
        ]

    def anthropic_tools(self) -> list[dict[str, Any]]:
        return self.tools

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        self.calls.append((name, arguments))
        if name in self.errors:
            return self.errors[name], True
        return json.dumps(self.results.get(name, {})), False

    @property
    def called_tools(self) -> list[str]:
        return [name for name, _ in self.calls]
