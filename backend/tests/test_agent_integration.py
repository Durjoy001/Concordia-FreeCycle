"""backend -> orchestrator -> real MCP server -> (stubbed) Claude.

The only fake in this chain is the Anthropic client. The MCP server runs in-process
over the real MCP protocol and reads the same database the API writes to, so tool
routing, schema exchange and SQL are all genuine.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from agent import orchestrator
from tests.agent_stubs import StubAnthropic, final, tool_turn
from tests.conftest import TINY_PNG, ApiUser, create_listing

# conftest puts mcp-server on sys.path and provides the `live_mcp` fixture.
import claude as mcp_claude  # noqa: E402  (mcp-server module)


class McpClaudeStub:
    """Stub for the MCP server's own Anthropic client."""

    def __init__(self, *payloads: dict[str, Any]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict[str, Any]] = []
        outer = self

        class Messages:
            async def create(self, **kwargs: Any) -> Any:
                outer.calls.append(kwargs)
                payload = outer.payloads.pop(0) if outer.payloads else {}
                text = json.dumps(payload)
                return type(
                    "Response",
                    (),
                    {
                        "content": [type("T", (), {"type": "text", "text": text})()],
                        "stop_reason": "end_turn",
                        "usage": type("U", (), {"input_tokens": 50, "output_tokens": 10})(),
                    },
                )()

        self.messages = Messages()


async def test_orchestrator_drives_the_real_mcp_tools(
    live_mcp, monkeypatch: pytest.MonkeyPatch, owner: ApiUser, claimer: ApiUser, db
) -> None:
    """The full chain for run_matching: flag_prohibited, then match_wishlist."""
    from app.models import Listing, WishlistItem

    listing_id = create_listing(owner, title="Ikea study desk")["id"]
    db.add(WishlistItem(user_id=claimer.id, keywords="table for studying", category="furniture"))
    db.commit()
    wishlist_item_id = db.query(WishlistItem).one().id

    # The MCP tools' Claude calls, in the order the tools will make them.
    mcp_stub = McpClaudeStub(
        {"flagged": False, "reason": None},
        {
            "matches": [
                {
                    "user_id": claimer.id,
                    "wishlist_item_id": wishlist_item_id,
                    "score": 0.92,
                    "rationale": "'table for studying' is exactly this study desk.",
                }
            ]
        },
    )
    mcp_claude.set_client(mcp_stub)

    # The orchestrator's own Claude calls: it decides to use both tools, then answers.
    monkeypatch.setattr(
        orchestrator,
        "_client",
        lambda: StubAnthropic(
            tool_turn(("flag_prohibited", {"photo_path": None, "title": "Ikea study desk",
                                           "description": "d"})),
            tool_turn(("match_wishlist", {"listing_id": listing_id})),
            final(
                {
                    "flagged": False,
                    "matches": [
                        {
                            "user_id": claimer.id,
                            "wishlist_item_id": wishlist_item_id,
                            "score": 0.92,
                            "rationale": "'table for studying' is exactly this study desk.",
                        }
                    ],
                    "summary": "Listing is clean and matches one wishlist.",
                }
            ),
        ),
    )

    result = await orchestrator.run_matching(
        listing_id, title="Ikea study desk", description="White desk"
    )

    assert result.tools_used() == ["flag_prohibited", "match_wishlist"]
    assert all(call.ok for call in result.tool_calls)
    assert result.data["matches"][0]["user_id"] == claimer.id

    # match_wishlist really read the database: the wishlist text reached its prompt.
    match_prompt = mcp_stub.calls[1]["messages"][0]["content"][0]["text"]
    assert "table for studying" in match_prompt
    assert "Ikea study desk" in match_prompt
    assert db.get(Listing, listing_id) is not None


async def test_the_vision_tool_receives_the_real_uploaded_image(
    live_mcp, monkeypatch: pytest.MonkeyPatch, owner: ApiUser
) -> None:
    """process_new_listing_photo -> create_listing_from_photo reads the stored file."""
    import base64

    from app.services.storage import get_storage

    key = get_storage().save(
        __import__("io").BytesIO(TINY_PNG), prefix=f"drafts/{owner.id}", content_type="image/png"
    )

    mcp_stub = McpClaudeStub(
        {
            "title": "Ikea Malm desk",
            "description": "White laminate desk with light scuffing.",
            "category": "furniture",
            "condition": "good",
            "confidence": 0.78,
        },
        {"flagged": False, "reason": None},
    )
    mcp_claude.set_client(mcp_stub)
    monkeypatch.setattr(
        orchestrator,
        "_client",
        lambda: StubAnthropic(
            tool_turn(("create_listing_from_photo", {"photo_path": key})),
            tool_turn(("flag_prohibited", {"photo_path": key, "title": "Ikea Malm desk",
                                           "description": "White laminate desk."})),
            final(
                {
                    "title": "Ikea Malm desk",
                    "description": "White laminate desk with light scuffing.",
                    "category": "furniture",
                    "condition": "good",
                    "confidence": 0.78,
                    "flagged": False,
                    "flag_reason": None,
                    "summary": "Drafted from the photo; nothing prohibited.",
                }
            ),
        ),
    )

    result = await orchestrator.process_new_listing_photo(key)

    assert result.tools_used() == ["create_listing_from_photo", "flag_prohibited"]
    assert result.data["category"] == "furniture"
    # The actual PNG bytes were base64'd into the vision request.
    image_block = next(
        block
        for block in mcp_stub.calls[0]["messages"][0]["content"]
        if block["type"] == "image"
    )
    assert base64.standard_b64decode(image_block["source"]["data"]) == TINY_PNG


async def test_an_mcp_tool_error_reaches_claude_through_the_real_protocol(
    live_mcp, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing listing produces isError over MCP, which the loop feeds back."""
    mcp_claude.set_client(McpClaudeStub())
    monkeypatch.setattr(
        orchestrator,
        "_client",
        lambda: StubAnthropic(
            tool_turn(("match_wishlist", {"listing_id": 999999})),
            final({"flagged": False, "matches": [],
                   "summary": "The listing could not be found."}),
        ),
    )
    result = await orchestrator.run_matching(999999, title="ghost", description="")

    assert result.tool_calls[0].ok is False
    assert "999999 was not found" in (result.tool_calls[0].error or "")
    assert result.data["matches"] == []


async def test_the_orchestrator_sees_all_five_tools_over_mcp(live_mcp) -> None:
    import mcp

    async with mcp.Client(live_mcp) as session:
        tools = await session.list_tools()
        toolbox = orchestrator.McpToolbox(session, tools.tools)
        offered = toolbox.anthropic_tools()

    assert {tool["name"] for tool in offered} == {
        "create_listing_from_photo", "classify_item", "flag_prohibited",
        "match_wishlist", "draft_coordination",
    }
    # Claude is given the schemas the MCP server itself advertises.
    for tool in offered:
        assert tool["input_schema"]["type"] == "object"
        assert tool["description"]
