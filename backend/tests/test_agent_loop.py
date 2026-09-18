"""The orchestrator's agentic loop, tool routing, retries and token accounting.

No network: the Anthropic client is a stub and the MCP toolbox is either a fake or
the real MCP server running in-process.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic
import httpx2
import pytest

from agent import orchestrator
from agent.orchestrator import AgentTask, AgentUnavailable
from tests.agent_stubs import FakeToolbox, StubAnthropic, final, tool_turn


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record backoff delays instead of waiting them out."""
    delays: list[float] = []

    async def _sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr(orchestrator.asyncio, "sleep", _sleep)
    return delays


def install(monkeypatch: pytest.MonkeyPatch, stub: StubAnthropic) -> StubAnthropic:
    monkeypatch.setattr(orchestrator, "_client", lambda: stub)
    return stub


async def run(toolbox: FakeToolbox, task: AgentTask = AgentTask.RUN_MATCHING) -> Any:
    return await orchestrator.run_agent(
        task=task,
        system="test system prompt",
        user_message="do the thing",
        schema=orchestrator.MATCHING_SCHEMA,
        toolbox=toolbox,
    )


# ------------------------------------------------------------------ the loop


async def test_claude_chooses_the_tools_and_the_loop_executes_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The documented flow: flag_prohibited, then (clean) match_wishlist, then answer."""
    install(
        monkeypatch,
        StubAnthropic(
            tool_turn(("flag_prohibited", {"photo_path": None, "title": "Desk",
                                           "description": "d"})),
            tool_turn(("match_wishlist", {"listing_id": 10})),
            final(
                {
                    "flagged": False,
                    "matches": [
                        {"user_id": 2, "wishlist_item_id": 100, "score": 0.9,
                         "rationale": "matches 'table for studying'"}
                    ],
                    "summary": "Clean listing, one match.",
                }
            ),
        ),
    )
    toolbox = FakeToolbox(
        {
            "flag_prohibited": {"flagged": False, "reason": None},
            "match_wishlist": {
                "matches": [
                    {"user_id": 2, "wishlist_item_id": 100, "score": 0.9, "rationale": "r"}
                ]
            },
        }
    )
    result = await run(toolbox)

    # Tool routing: the orchestrator executed exactly what Claude asked for, in order.
    assert toolbox.called_tools == ["flag_prohibited", "match_wishlist"]
    assert result.tools_used() == ["flag_prohibited", "match_wishlist"]
    assert result.data["matches"][0]["wishlist_item_id"] == 100
    assert result.summary == "Clean listing, one match."
    assert result.iterations == 3
    # Tokens are accumulated across every turn of the loop, not just the last.
    assert result.input_tokens == 300
    assert result.output_tokens == 60
    assert result.latency_ms >= 0
    # Every call is logged with its latency.
    assert all(call.latency_ms >= 0 and call.ok for call in result.tool_calls)


async def test_the_mcp_tool_schemas_are_what_claude_is_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = install(monkeypatch, StubAnthropic(final({"flagged": False, "matches": [],
                                                     "summary": "none"})))
    toolbox = FakeToolbox()
    await run(toolbox)
    offered = {tool["name"] for tool in stub.last_request["tools"]}
    assert offered == {
        "flag_prohibited", "match_wishlist", "create_listing_from_photo",
        "draft_coordination", "classify_item",
    }
    # The final answer is schema-constrained.
    assert stub.last_request["output_config"]["format"]["type"] == "json_schema"
    assert stub.last_request["model"] == "claude-sonnet-4-6"
    assert stub.last_request["system"] == "test system prompt"


async def test_an_immediate_answer_uses_no_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, StubAnthropic(final({"flagged": False, "matches": [],
                                              "summary": "nothing to do"})))
    toolbox = FakeToolbox()
    result = await run(toolbox)
    assert toolbox.calls == []
    assert result.tool_call_count == 0
    assert result.iterations == 1


async def test_parallel_tool_calls_return_in_one_user_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = install(
        monkeypatch,
        StubAnthropic(
            tool_turn(("flag_prohibited", {"title": "a"}), ("classify_item", {"title": "a"})),
            final({"flagged": False, "matches": [], "summary": "done"}),
        ),
    )
    toolbox = FakeToolbox()
    result = await run(toolbox)

    assert toolbox.called_tools == ["flag_prohibited", "classify_item"]
    assert result.tool_call_count == 2
    # Both tool_results must arrive in a single user message, or Claude learns to
    # stop making parallel calls.
    messages = stub.last_request["messages"]
    tool_result_messages = [
        message
        for message in messages
        if message["role"] == "user"
        and isinstance(message["content"], list)
        and all(block.get("type") == "tool_result" for block in message["content"])
    ]
    assert len(tool_result_messages) == 1
    assert len(tool_result_messages[0]["content"]) == 2


async def test_a_tool_error_is_fed_back_and_the_loop_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = install(
        monkeypatch,
        StubAnthropic(
            tool_turn(("match_wishlist", {"listing_id": 999})),
            final({"flagged": False, "matches": [], "summary": "Listing 999 was not found."}),
        ),
    )
    toolbox = FakeToolbox(errors={"match_wishlist": "Listing 999 was not found."})
    result = await run(toolbox)

    assert result.tool_calls[0].ok is False
    assert result.tool_calls[0].error == "Listing 999 was not found."
    assert result.data["matches"] == []
    # The error reached Claude flagged as an error, rather than looking like a result.
    tool_result = stub.last_request["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert "not found" in tool_result["content"]


async def test_a_raising_toolbox_does_not_kill_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    install(
        monkeypatch,
        StubAnthropic(
            tool_turn(("match_wishlist", {"listing_id": 1})),
            final({"flagged": False, "matches": [], "summary": "tool broke"}),
        ),
    )

    class BrokenToolbox(FakeToolbox):
        async def call(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
            raise RuntimeError("transport exploded")

    result = await run(BrokenToolbox())
    assert result.tool_calls[0].ok is False
    assert "transport exploded" in (result.tool_calls[0].error or "")


async def test_the_iteration_cap_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tool-calling loop that never answers must terminate."""
    install(
        monkeypatch,
        StubAnthropic(*[tool_turn(("flag_prohibited", {"title": "x"})) for _ in range(10)]),
    )
    with pytest.raises(AgentUnavailable, match="did not finish within"):
        await run(FakeToolbox())


async def test_a_refusal_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, StubAnthropic(final({"flagged": False, "matches": [], "summary": ""},
                                             stop_reason="refusal")))
    with pytest.raises(AgentUnavailable, match="declined"):
        await run(FakeToolbox())


async def test_a_missing_final_answer_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.agent_stubs import StubMessage

    install(monkeypatch, StubAnthropic(StubMessage([])))
    with pytest.raises(AgentUnavailable, match="no final answer"):
        await run(FakeToolbox())


# ------------------------------------------------------------------ retries


async def test_transient_errors_are_retried_with_exponential_backoff(
    monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]
) -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    stub = install(
        monkeypatch,
        StubAnthropic(
            anthropic.APIConnectionError(request=request),
            anthropic.APIConnectionError(request=request),
            final({"flagged": False, "matches": [], "summary": "recovered"}),
        ),
    )
    result = await run(FakeToolbox())

    assert result.summary == "recovered"
    assert stub.call_count == 3
    assert no_sleep == [0.5, 1.0]  # exponential


async def test_retries_are_bounded(monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]) -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    stub = install(
        monkeypatch,
        StubAnthropic(*[anthropic.APIConnectionError(request=request) for _ in range(5)]),
    )
    with pytest.raises(AgentUnavailable, match="unavailable after 3 attempts"):
        await run(FakeToolbox())
    assert stub.call_count == 3  # AGENT_MAX_RETRIES
    assert len(no_sleep) == 2    # no sleep after the final attempt


async def test_a_non_retryable_status_error_fails_immediately(
    monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]
) -> None:
    response = httpx2.Response(
        400,
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"),
        json={"error": {"message": "bad request"}},
    )
    stub = install(
        monkeypatch,
        StubAnthropic(
            anthropic.BadRequestError("bad request", response=response, body=None),
            final({"flagged": False, "matches": [], "summary": "never reached"}),
        ),
    )
    with pytest.raises(AgentUnavailable, match="Claude API error 400"):
        await run(FakeToolbox())
    assert stub.call_count == 1  # a 400 will not improve on a retry
    assert no_sleep == []


# ------------------------------------------------------------------ observability


async def test_every_tool_call_is_logged_as_structured_json(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    install(
        monkeypatch,
        StubAnthropic(
            tool_turn(("flag_prohibited", {"title": "Desk", "description": "d"})),
            final({"flagged": False, "matches": [], "summary": "clean"}),
        ),
    )
    with caplog.at_level("INFO", logger="freecycle.agent"):
        await run(FakeToolbox())

    records = [json.loads(record.message) for record in caplog.records
               if record.name == "freecycle.agent"]
    tool_events = [record for record in records if record["event"] == "agent_tool_call"]
    run_events = [record for record in records if record["event"] == "agent_run"]

    assert len(tool_events) == 1
    assert tool_events[0]["tool"] == "flag_prohibited"
    assert tool_events[0]["arguments"] == {"title": "Desk", "description": "d"}
    assert tool_events[0]["latency_ms"] >= 0
    assert tool_events[0]["ok"] is True
    assert tool_events[0]["task"] == "run_matching"

    assert len(run_events) == 1
    assert run_events[0]["tools_used"] == ["flag_prohibited"]
    assert run_events[0]["input_tokens"] == 200
    assert run_events[0]["output_tokens"] == 40
    assert run_events[0]["iterations"] == 2


async def test_retries_are_logged(
    monkeypatch: pytest.MonkeyPatch, no_sleep: list[float], caplog: pytest.LogCaptureFixture
) -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    install(
        monkeypatch,
        StubAnthropic(
            anthropic.RateLimitError(
                "slow down",
                response=httpx2.Response(429, request=request),
                body=None,
            ),
            final({"flagged": False, "matches": [], "summary": "ok"}),
        ),
    )
    with caplog.at_level("WARNING", logger="freecycle.agent"):
        await run(FakeToolbox())
    retries = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "freecycle.agent" and "agent_api_retry" in record.message
    ]
    assert retries[0]["error"] == "RateLimitError"
    assert retries[0]["attempt"] == 1


# ------------------------------------------------------------------ entry points


async def test_entry_points_use_their_own_prompt_and_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each entry point must hand Claude its own task prompt and answer schema."""
    from agent import prompts

    class RecordingToolbox(FakeToolbox):
        pass

    captured: list[dict[str, Any]] = []

    async def fake_run_with_session(**kwargs: Any) -> Any:
        captured.append(kwargs)
        return orchestrator.AgentResult(task=kwargs["task"], data={}, summary="")

    monkeypatch.setattr(orchestrator, "_run_with_session", fake_run_with_session)

    await orchestrator.process_new_listing_photo("drafts/1/a.png")
    await orchestrator.moderate_listing(5, title="t", description="d")
    await orchestrator.run_matching(5, title="t", description="d")
    await orchestrator.draft_pickup_message(5, 9)

    assert [call["task"] for call in captured] == [
        AgentTask.DRAFT_LISTING,
        AgentTask.MODERATE_LISTING,
        AgentTask.RUN_MATCHING,
        AgentTask.DRAFT_PICKUP_MESSAGE,
    ]
    assert captured[0]["system"] == prompts.DRAFT_LISTING
    assert captured[1]["system"] == prompts.MODERATE_LISTING
    assert captured[2]["system"] == prompts.RUN_MATCHING
    assert captured[3]["system"] == prompts.DRAFT_PICKUP_MESSAGE
    assert captured[0]["schema"] is orchestrator.DRAFT_LISTING_SCHEMA
    assert captured[1]["schema"] is orchestrator.MODERATION_SCHEMA
    assert captured[2]["schema"] is orchestrator.MATCHING_SCHEMA
    assert captured[3]["schema"] is orchestrator.PICKUP_SCHEMA
    # Ids and paths reach the prompt, since the tools look everything else up.
    assert "drafts/1/a.png" in captured[0]["user_message"]
    assert "claim 9" in captured[3]["user_message"]


async def test_a_missing_api_key_is_agent_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent.config import get_settings

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")
    with pytest.raises(AgentUnavailable, match="ANTHROPIC_API_KEY"):
        await run(FakeToolbox())


async def test_an_unreachable_mcp_server_is_agent_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(orchestrator, "_mcp_target", lambda: "http://127.0.0.1:1/mcp")
    with pytest.raises(AgentUnavailable, match="Could not reach the MCP server"):
        await orchestrator.moderate_listing(1, title="t", description="d")
