"""Thin Claude wrapper shared by the MCP tools.

Every tool needs the same three things: a client, structured JSON back, and an
image encoded for vision input. The SDK's own retry (429 / 5xx / connection
errors, exponential backoff) is configured on the client here; the orchestrator
adds a second, coarser retry around whole tool calls.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Final

import anthropic
from anthropic.types import MessageParam

from config import get_settings

MEDIA_TYPES: Final[dict[str, str]] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

_client: anthropic.AsyncAnthropic | None = None


class ToolError(Exception):
    """A tool could not produce a result; surfaced to the caller as isError."""


def get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise ToolError("ANTHROPIC_API_KEY is not configured on the MCP server.")
        _client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            max_retries=3,
            timeout=settings.request_timeout_seconds,
        )
    return _client


def set_client(client: anthropic.AsyncAnthropic | None) -> None:
    """Inject a stub client (used by the test suite)."""
    global _client
    _client = client


def resolve_photo(photo_path: str) -> Path:
    """Map a storage key (or absolute path) onto a readable file under UPLOAD_DIR."""
    settings = get_settings()
    root = Path(settings.upload_dir).resolve()
    candidate = Path(photo_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / photo_path).resolve()

    if resolved != root and root not in resolved.parents:
        raise ToolError(f"Photo path {photo_path!r} is outside the upload directory.")
    if not resolved.is_file():
        raise ToolError(f"Photo {photo_path!r} was not found.")
    return resolved


def image_block(photo_path: str) -> dict[str, Any]:
    """A base64 image content block for Claude vision."""
    path = resolve_photo(photo_path)
    media_type = MEDIA_TYPES.get(path.suffix.lower())
    if media_type is None:
        raise ToolError(f"Unsupported image extension {path.suffix!r}.")
    data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data},
    }


async def structured(
    *,
    system: str,
    content: list[dict[str, Any]],
    schema: dict[str, Any],
    max_tokens: int = 2048,
) -> dict[str, Any]:
    """One Claude call constrained to `schema`, returned as a dict.

    `output_config.format` guarantees the first text block is schema-valid JSON, so
    no prose-stripping or brace-hunting is needed here.
    """
    client = get_client()
    settings = get_settings()
    messages: list[MessageParam] = [{"role": "user", "content": content}]

    try:
        response = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
    except anthropic.APIStatusError as exc:
        raise ToolError(f"Claude API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise ToolError(f"Could not reach the Claude API: {exc}") from exc

    if response.stop_reason == "refusal":
        raise ToolError("Claude declined to answer this request.")

    text = next((block.text for block in response.content if block.type == "text"), None)
    if not text:
        raise ToolError("Claude returned no text content.")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:  # pragma: no cover - schema-constrained
        raise ToolError(f"Claude returned malformed JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ToolError("Claude returned a non-object JSON payload.")

    usage = response.usage
    parsed["_usage"] = {
        "input_tokens": getattr(usage, "input_tokens", 0),
        "output_tokens": getattr(usage, "output_tokens", 0),
    }
    return parsed
