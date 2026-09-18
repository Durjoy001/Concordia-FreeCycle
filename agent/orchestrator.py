"""The agent orchestrator.

Claude is given the MCP server's tools and decides which to call, in what order;
this module executes those calls against the MCP server and loops until Claude
returns a final, schema-constrained answer. The backend never talks to Claude
directly and never calls an MCP tool itself.

    backend  ->  orchestrator  ->  MCP server  ->  Claude
                     |                  |
                     +-- agentic loop   +-- vision / classification / matching

Every tool call is logged as one JSON line (tool, arguments, latency, tokens) on
the `freecycle.agent` logger - that is the observability story.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

import anthropic
import mcp
from anthropic.types import MessageParam, ToolParam

from . import prompts
from .config import get_settings

logger = logging.getLogger("freecycle.agent")


class AgentTask(str, Enum):
    """Mirrors app.models.enums.AgentTask."""

    DRAFT_LISTING = "draft_listing"
    MODERATE_LISTING = "moderate_listing"
    RUN_MATCHING = "run_matching"
    DRAFT_PICKUP_MESSAGE = "draft_pickup_message"


class AgentUnavailable(Exception):
    """The agent layer could not run. Callers must degrade, never fail the request."""


class AgentBudgetExceeded(Exception):
    """The user has used up their daily agent budget."""


# --------------------------------------------------------------------------- results


@dataclass(slots=True)
class ToolCallLog:
    tool: str
    arguments: dict[str, Any]
    latency_ms: float
    ok: bool
    error: str | None = None


@dataclass(slots=True)
class AgentResult:
    """What an entry point returns: the answer plus everything worth recording."""

    task: AgentTask
    data: dict[str, Any]
    summary: str
    tool_calls: list[ToolCallLog] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    iterations: int = 0

    @property
    def tool_call_count(self) -> int:
        return len(self.tool_calls)

    def tools_used(self) -> list[str]:
        return [call.tool for call in self.tool_calls]


@runtime_checkable
class BudgetGuard(Protocol):
    """Supplied by the backend, which owns the per-user run counts."""

    def check(self, user_id: int, task: AgentTask) -> None:
        """Raise AgentBudgetExceeded when the user is over their daily allowance."""

    def record(self, user_id: int, task: AgentTask, result: AgentResult | None,
               error: str | None) -> None:
        """Persist the outcome of one run."""


# --------------------------------------------------------------------------- schemas

_SUMMARY = {
    "type": "string",
    "maxLength": 400,
    "description": "One or two sentences on what you did and found.",
}
_CATEGORIES = ["furniture", "books", "electronics", "kitchen", "clothing", "other"]
_CONDITIONS = ["like_new", "good", "fair", "worn"]


def _strict(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


DRAFT_LISTING_SCHEMA = _strict(
    {
        "title": {"type": "string", "maxLength": 140},
        "description": {"type": "string", "maxLength": 1200},
        "category": {"type": "string", "enum": _CATEGORIES},
        "condition": {"type": "string", "enum": _CONDITIONS},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "flagged": {"type": "boolean"},
        "flag_reason": {"type": ["string", "null"], "maxLength": 300},
        "summary": _SUMMARY,
    },
    ["title", "description", "category", "condition", "confidence", "flagged", "flag_reason",
     "summary"],
)

MODERATION_SCHEMA = _strict(
    {
        "flagged": {"type": "boolean"},
        "flag_reason": {"type": ["string", "null"], "maxLength": 300},
        "summary": _SUMMARY,
    },
    ["flagged", "flag_reason", "summary"],
)

MATCHING_SCHEMA = _strict(
    {
        "flagged": {"type": "boolean", "description": "True if the listing was flagged."},
        "matches": {
            "type": "array",
            "maxItems": 25,
            "items": _strict(
                {
                    "user_id": {"type": "integer"},
                    "wishlist_item_id": {"type": "integer"},
                    "score": {"type": "number", "minimum": 0, "maximum": 1},
                    "rationale": {"type": "string", "maxLength": 240},
                },
                ["user_id", "wishlist_item_id", "score", "rationale"],
            ),
        },
        "summary": _SUMMARY,
    },
    ["flagged", "matches", "summary"],
)

PICKUP_SCHEMA = _strict(
    {"message": {"type": "string", "maxLength": 900}, "summary": _SUMMARY},
    ["message", "summary"],
)


# --------------------------------------------------------------------------- MCP session


class McpToolbox:
    """An open MCP session, exposing its tools in Anthropic tool format."""

    def __init__(self, session: mcp.Client, tools: Sequence[mcp.types.Tool]) -> None:
        self._session = session
        self._tools = list(tools)

    @property
    def tool_names(self) -> list[str]:
        return [tool.name for tool in self._tools]

    def anthropic_tools(self) -> list[ToolParam]:
        """Claude decides from these; the schemas come from the MCP server itself."""
        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.input_schema,
            }
            for tool in self._tools
        ]

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        """Execute one MCP tool call. Returns (content for Claude, is_error)."""
        result = await self._session.call_tool(name, arguments)
        if result.structured_content is not None and not result.is_error:
            return json.dumps(result.structured_content), False
        texts = [block.text for block in result.content if getattr(block, "type", None) == "text"]
        return ("\n".join(texts) or "The tool returned no content.", bool(result.is_error))


def _mcp_target() -> Any:
    """The MCP server as the client should reach it, per MCP_TRANSPORT."""
    settings = get_settings()
    if settings.mcp_transport == "stdio":
        return mcp.StdioServerParameters(
            command=settings.mcp_server_command, args=settings.mcp_server_arg_list
        )
    return settings.mcp_server_url


# --------------------------------------------------------------------------- the loop


def _client() -> anthropic.AsyncAnthropic:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise AgentUnavailable("ANTHROPIC_API_KEY is not configured.")
    # max_retries=0: retries and backoff are this module's job (see _create), so the
    # structured log records every attempt instead of hiding them inside the SDK.
    return anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        max_retries=0,
        timeout=settings.agent_request_timeout,
    )


_RETRYABLE = (
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
)


async def _create(
    client: anthropic.AsyncAnthropic,
    *,
    system: str,
    messages: list[MessageParam],
    tools: list[ToolParam],
    schema: dict[str, Any],
) -> Any:
    """One Claude request, retried with exponential backoff on transient failures."""
    settings = get_settings()
    delay = settings.agent_retry_base_delay
    last: Exception | None = None

    for attempt in range(1, settings.agent_max_retries + 1):
        try:
            return await client.messages.create(
                model=settings.anthropic_model,
                max_tokens=settings.agent_max_tokens,
                system=system,
                messages=messages,
                tools=tools,
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except _RETRYABLE as exc:
            last = exc
            logger.warning(
                json.dumps(
                    {
                        "event": "agent_api_retry",
                        "attempt": attempt,
                        "max_attempts": settings.agent_max_retries,
                        "error": type(exc).__name__,
                    }
                )
            )
            if attempt == settings.agent_max_retries:
                break
            await asyncio.sleep(delay)
            delay *= 2
        except anthropic.APIStatusError as exc:
            # 400/401/403/404 will not improve on a retry.
            raise AgentUnavailable(f"Claude API error {exc.status_code}: {exc.message}") from exc

    raise AgentUnavailable(f"Claude API unavailable after {settings.agent_max_retries} attempts: {last}")


async def run_agent(
    *,
    task: AgentTask,
    system: str,
    user_message: str,
    schema: dict[str, Any],
    toolbox: McpToolbox,
) -> AgentResult:
    """The agentic loop: Claude picks tools, we execute them, until it answers."""
    settings = get_settings()
    client = _client()
    tools = toolbox.anthropic_tools()
    messages: list[MessageParam] = [{"role": "user", "content": user_message}]

    result = AgentResult(task=task, data={}, summary="")
    started = time.perf_counter()

    for iteration in range(1, settings.agent_max_tool_iterations + 1):
        result.iterations = iteration
        response = await _create(
            client, system=system, messages=messages, tools=tools, schema=schema
        )
        usage = response.usage
        result.input_tokens += getattr(usage, "input_tokens", 0) or 0
        result.output_tokens += getattr(usage, "output_tokens", 0) or 0

        if response.stop_reason == "refusal":
            raise AgentUnavailable("Claude declined to complete this task.")

        tool_uses = [block for block in response.content if block.type == "tool_use"]
        if not tool_uses:
            result.data = _final_answer(response)
            result.summary = str(result.data.pop("summary", ""))
            result.latency_ms = round((time.perf_counter() - started) * 1000, 1)
            _log_run(result)
            return result

        messages.append({"role": "assistant", "content": response.content})

        # All results for one assistant turn go back in a single user message.
        tool_results: list[dict[str, Any]] = []
        for block in tool_uses:
            arguments = dict(block.input) if isinstance(block.input, dict) else {}
            call_started = time.perf_counter()
            try:
                content, is_error = await toolbox.call(block.name, arguments)
            except Exception as exc:  # noqa: BLE001 - a broken tool must not kill the run
                content, is_error = f"Tool call failed: {exc}", True
            latency = round((time.perf_counter() - call_started) * 1000, 1)

            log = ToolCallLog(
                tool=block.name,
                arguments=arguments,
                latency_ms=latency,
                ok=not is_error,
                error=content if is_error else None,
            )
            result.tool_calls.append(log)
            _log_tool_call(task, log)

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                    "is_error": is_error,
                }
            )
        messages.append({"role": "user", "content": tool_results})

    raise AgentUnavailable(
        f"Agent did not finish within {settings.agent_max_tool_iterations} iterations."
    )


def _final_answer(response: Any) -> dict[str, Any]:
    text = next((block.text for block in response.content if block.type == "text"), None)
    if not text:
        raise AgentUnavailable("Claude returned no final answer.")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:  # pragma: no cover - schema-constrained
        raise AgentUnavailable(f"Claude returned malformed JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise AgentUnavailable("Claude returned a non-object final answer.")
    return parsed


def _log_tool_call(task: AgentTask, log: ToolCallLog) -> None:
    logger.info(
        json.dumps(
            {
                "event": "agent_tool_call",
                "task": task.value,
                "tool": log.tool,
                "arguments": log.arguments,
                "latency_ms": log.latency_ms,
                "ok": log.ok,
                "error": log.error,
            }
        )
    )


def _log_run(result: AgentResult) -> None:
    logger.info(
        json.dumps(
            {
                "event": "agent_run",
                "task": result.task.value,
                "tools_used": result.tools_used(),
                "iterations": result.iterations,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "latency_ms": result.latency_ms,
            }
        )
    )


# --------------------------------------------------------------------------- entry points


async def _run_with_session(
    *,
    task: AgentTask,
    system: str,
    user_message: str,
    schema: dict[str, Any],
    user_id: int | None = None,
    guard: BudgetGuard | None = None,
) -> AgentResult:
    """Open an MCP session, run the loop, account for the run."""
    if guard is not None and user_id is not None:
        guard.check(user_id, task)  # raises AgentBudgetExceeded

    result: AgentResult | None = None
    error: str | None = None
    try:
        try:
            async with mcp.Client(_mcp_target()) as session:
                tools = await session.list_tools()
                toolbox = McpToolbox(session, tools.tools)
                result = await run_agent(
                    task=task,
                    system=system,
                    user_message=user_message,
                    schema=schema,
                    toolbox=toolbox,
                )
        except (AgentUnavailable, AgentBudgetExceeded):
            raise
        except Exception as exc:  # noqa: BLE001 - MCP transport / startup failures
            raise AgentUnavailable(f"Could not reach the MCP server: {exc}") from exc
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        if guard is not None and user_id is not None:
            guard.record(user_id, task, result, error)
    return result  # type: ignore[return-value]


async def process_new_listing_photo(
    photo_path: str, *, user_id: int | None = None, guard: BudgetGuard | None = None
) -> AgentResult:
    """Draft listing fields from a photo, moderated before the student sees them."""
    return await _run_with_session(
        task=AgentTask.DRAFT_LISTING,
        system=prompts.DRAFT_LISTING,
        user_message=(
            f"A student uploaded the photo at storage path {photo_path!r} and wants the "
            "listing form filled in. Draft the fields and check the item is allowed."
        ),
        schema=DRAFT_LISTING_SCHEMA,
        user_id=user_id,
        guard=guard,
    )


async def moderate_listing(
    listing_id: int,
    *,
    title: str,
    description: str,
    photo_path: str | None = None,
    user_id: int | None = None,
    guard: BudgetGuard | None = None,
) -> AgentResult:
    """Decide whether a newly created listing must be hidden."""
    photo = repr(photo_path) if photo_path else "none"
    return await _run_with_session(
        task=AgentTask.MODERATE_LISTING,
        system=prompts.MODERATE_LISTING,
        user_message=(
            f"Moderate listing {listing_id}.\n"
            f"photo_path: {photo}\ntitle: {title}\ndescription: {description or '(none)'}"
        ),
        schema=MODERATION_SCHEMA,
        user_id=user_id,
        guard=guard,
    )


async def run_matching(
    listing_id: int,
    *,
    title: str,
    description: str,
    photo_path: str | None = None,
    user_id: int | None = None,
    guard: BudgetGuard | None = None,
) -> AgentResult:
    """Find wishlists this listing satisfies, after confirming it is allowed."""
    photo = repr(photo_path) if photo_path else "none"
    return await _run_with_session(
        task=AgentTask.RUN_MATCHING,
        system=prompts.RUN_MATCHING,
        user_message=(
            f"Listing {listing_id} was just posted. Check it is allowed, then find the "
            "students whose wishlists it satisfies.\n"
            f"photo_path: {photo}\ntitle: {title}\ndescription: {description or '(none)'}"
        ),
        schema=MATCHING_SCHEMA,
        user_id=user_id,
        guard=guard,
    )


async def draft_pickup_message(
    listing_id: int, claim_id: int, *, user_id: int | None = None,
    guard: BudgetGuard | None = None,
) -> AgentResult:
    """Draft the handover message for an accepted claim."""
    return await _run_with_session(
        task=AgentTask.DRAFT_PICKUP_MESSAGE,
        system=prompts.DRAFT_PICKUP_MESSAGE,
        user_message=(
            f"The owner of listing {listing_id} accepted claim {claim_id}. "
            "Draft the pickup message."
        ),
        schema=PICKUP_SCHEMA,
        user_id=user_id,
        guard=guard,
    )
