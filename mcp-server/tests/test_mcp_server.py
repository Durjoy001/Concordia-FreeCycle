"""The MCP server, driven through a real in-process MCP client session."""

from __future__ import annotations

import base64
import json
from typing import Any

import mcp
import pytest
import sqlalchemy as sa

import claude
from server import build_server, build_tools
from tests.conftest import add_claim, add_listing, add_user, add_wishlist

EXPECTED_TOOLS = {
    "create_listing_from_photo",
    "classify_item",
    "flag_prohibited",
    "match_wishlist",
    "draft_coordination",
}


async def call(name: str, arguments: dict[str, Any]) -> mcp.types.CallToolResult:
    """Round-trip one tool call over the MCP protocol, in process."""
    async with mcp.Client(build_server()) as client:
        return await client.call_tool(name, arguments)


# ------------------------------------------------------------------ registration


async def test_all_five_tools_are_advertised() -> None:
    async with mcp.Client(build_server()) as client:
        result = await client.list_tools()
    assert {tool.name for tool in result.tools} == EXPECTED_TOOLS


async def test_every_tool_has_strict_input_and_output_schemas() -> None:
    for tool in build_tools():
        for label, schema in (("input", tool.input_schema), ("output", tool.output_schema)):
            assert schema is not None, f"{tool.name} has no {label} schema"
            assert schema["type"] == "object"
            assert schema["additionalProperties"] is False, f"{tool.name} {label} is not strict"
            assert schema["required"], f"{tool.name} {label} has no required keys"
            assert tool.description and len(tool.description) > 40


def test_enum_schemas_match_the_api_enums() -> None:
    """The MCP server duplicates the enums deliberately - keep them honest."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
    from app.models.enums import Category, Condition

    import schemas

    assert schemas.CATEGORIES == [member.value for member in Category]
    assert schemas.CONDITIONS == [member.value for member in Condition]


async def test_unknown_tool_is_an_error_not_a_crash() -> None:
    result = await call("no_such_tool", {})
    assert result.is_error
    assert "Unknown tool" in result.content[0].text


# ------------------------------------------------------ create_listing_from_photo


async def test_create_listing_from_photo_sends_the_image_and_returns_fields(
    stub_claude, photo: str
) -> None:
    stub = stub_claude(
        {
            "title": "Ikea Malm desk",
            "description": "White laminate desk with a small ink mark on the top right.",
            "category": "furniture",
            "condition": "good",
            "confidence": 0.82,
        }
    )
    result = await call("create_listing_from_photo", {"photo_path": photo})

    assert not result.is_error
    assert result.structured_content == {
        "title": "Ikea Malm desk",
        "description": "White laminate desk with a small ink mark on the top right.",
        "category": "furniture",
        "condition": "good",
        "confidence": 0.82,
    }
    # The text block carries the same JSON for clients that ignore structuredContent.
    assert json.loads(result.content[0].text) == result.structured_content

    request = stub.last_call
    assert request["model"] == "claude-sonnet-4-6"
    blocks = request["messages"][0]["content"]
    image = next(block for block in blocks if block["type"] == "image")
    assert image["source"]["media_type"] == "image/png"
    assert base64.standard_b64decode(image["source"]["data"])[:4] == b"\x89PNG"
    # Structured output is what guarantees schema-valid fields.
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert request["output_config"]["format"]["schema"]["required"] == [
        "title", "description", "category", "condition", "confidence",
    ]


async def test_create_listing_from_photo_rejects_a_missing_photo(stub_claude) -> None:
    stub_claude({})
    result = await call("create_listing_from_photo", {"photo_path": "listings/1/nope.png"})
    assert result.is_error
    assert "not found" in result.content[0].text


@pytest.mark.parametrize("bad_path", ["../../etc/passwd", "/etc/passwd"])
async def test_create_listing_from_photo_refuses_paths_outside_uploads(
    stub_claude, bad_path: str
) -> None:
    stub_claude({})
    result = await call("create_listing_from_photo", {"photo_path": bad_path})
    assert result.is_error
    assert "outside the upload directory" in result.content[0].text or "not found" in (
        result.content[0].text
    )


async def test_missing_required_argument_is_reported(stub_claude) -> None:
    stub_claude({})
    result = await call("create_listing_from_photo", {})
    assert result.is_error


# ------------------------------------------------------------------ classify_item


async def test_classify_item_is_text_only(stub_claude) -> None:
    stub = stub_claude({"category": "books", "condition_hint": "Described as 'barely used'."})
    result = await call(
        "classify_item",
        {"title": "Calculus textbook", "description": "Barely used, 8th edition."},
    )
    assert result.structured_content["category"] == "books"
    blocks = stub.last_call["messages"][0]["content"]
    assert all(block["type"] == "text" for block in blocks)
    assert "Calculus textbook" in blocks[0]["text"]


async def test_classify_item_handles_an_empty_description(stub_claude) -> None:
    stub = stub_claude({"category": "other", "condition_hint": "The text does not say."})
    result = await call("classify_item", {"title": "Mystery box", "description": ""})
    assert not result.is_error
    assert "(none provided)" in stub.last_call["messages"][0]["content"][0]["text"]


# ------------------------------------------------------------------ flag_prohibited


async def test_flag_prohibited_flags_with_a_reason(stub_claude) -> None:
    stub_claude({"flagged": True, "reason": "Alcohol cannot be given away here."})
    result = await call(
        "flag_prohibited",
        {"photo_path": None, "title": "Free vodka", "description": "Unopened bottle"},
    )
    assert result.structured_content == {
        "flagged": True,
        "reason": "Alcohol cannot be given away here.",
    }


async def test_flag_prohibited_passes_clean_listings(stub_claude) -> None:
    stub_claude({"flagged": False, "reason": None})
    result = await call(
        "flag_prohibited", {"photo_path": None, "title": "Free desk", "description": "White desk"}
    )
    assert result.structured_content == {"flagged": False, "reason": None}


async def test_flag_prohibited_includes_the_photo_when_given(stub_claude, photo: str) -> None:
    stub = stub_claude({"flagged": False, "reason": None})
    await call("flag_prohibited", {"photo_path": photo, "title": "Desk", "description": "d"})
    blocks = stub.last_call["messages"][0]["content"]
    assert blocks[0]["type"] == "image"


async def test_flag_prohibited_works_without_a_photo(stub_claude) -> None:
    stub = stub_claude({"flagged": False, "reason": None})
    await call("flag_prohibited", {"photo_path": None, "title": "Desk", "description": "d"})
    blocks = stub.last_call["messages"][0]["content"]
    assert all(block["type"] == "text" for block in blocks)


async def test_flag_prohibited_clears_a_reason_on_an_unflagged_verdict(stub_claude) -> None:
    """Claude occasionally explains itself while answering 'not flagged'."""
    stub_claude({"flagged": False, "reason": "Looks fine to me."})
    result = await call(
        "flag_prohibited", {"photo_path": None, "title": "Desk", "description": "d"}
    )
    assert result.structured_content == {"flagged": False, "reason": None}


async def test_flag_prohibited_supplies_a_reason_when_one_is_missing(stub_claude) -> None:
    stub_claude({"flagged": True, "reason": None})
    result = await call(
        "flag_prohibited", {"photo_path": None, "title": "Free beer", "description": ""}
    )
    assert result.structured_content["flagged"] is True
    assert result.structured_content["reason"]  # never a flag the owner cannot read


# ------------------------------------------------------------------ match_wishlist


async def test_match_wishlist_reads_the_db_and_returns_scored_matches(
    stub_claude, engine: sa.Engine
) -> None:
    add_user(engine, 1, "Owner Olivia")
    add_user(engine, 2, "Wanting Wendy")
    add_listing(engine, 10, owner_id=1, title="Ikea study desk")
    add_wishlist(engine, 100, user_id=2, keywords="table for studying", category="furniture")

    stub = stub_claude(
        {
            "matches": [
                {
                    "user_id": 2,
                    "wishlist_item_id": 100,
                    "score": 0.91,
                    "rationale": "'table for studying' is this study desk.",
                }
            ]
        }
    )
    result = await call("match_wishlist", {"listing_id": 10})

    assert result.structured_content["matches"][0]["wishlist_item_id"] == 100
    # The listing and the candidate wishlists reached the prompt from the database.
    prompt = stub.last_call["messages"][0]["content"][0]["text"]
    assert "Ikea study desk" in prompt
    assert "table for studying" in prompt
    assert "wishlist_item_id=100" in prompt


async def test_match_wishlist_excludes_the_owners_own_wishlist(
    stub_claude, engine: sa.Engine
) -> None:
    add_user(engine, 1, "Owner Olivia")
    add_user(engine, 2, "Other Oscar")
    add_listing(engine, 10, owner_id=1)
    add_wishlist(engine, 100, user_id=1, keywords="desk")   # the owner's own
    add_wishlist(engine, 101, user_id=2, keywords="a desk")

    stub = stub_claude({"matches": []})
    await call("match_wishlist", {"listing_id": 10})
    prompt = stub.last_call["messages"][0]["content"][0]["text"]
    assert "wishlist_item_id=101" in prompt
    assert "wishlist_item_id=100" not in prompt


async def test_match_wishlist_skips_the_api_call_when_no_wishlists_exist(
    stub_claude, engine: sa.Engine
) -> None:
    add_user(engine, 1, "Owner Olivia")
    add_listing(engine, 10, owner_id=1)
    stub = stub_claude({"matches": [{"user_id": 9, "wishlist_item_id": 9, "score": 1.0,
                                     "rationale": "should never be used"}]})
    result = await call("match_wishlist", {"listing_id": 10})
    assert result.structured_content == {"matches": []}
    assert stub.calls == []  # no tokens spent when nobody is waiting


async def test_match_wishlist_drops_below_threshold_matches(
    stub_claude, engine: sa.Engine
) -> None:
    add_user(engine, 1, "Owner")
    add_user(engine, 2, "Wanter")
    add_listing(engine, 10, owner_id=1)
    add_wishlist(engine, 100, user_id=2, keywords="desk lamp")
    add_wishlist(engine, 101, user_id=2, keywords="a study table")

    stub_claude(
        {
            "matches": [
                {"user_id": 2, "wishlist_item_id": 100, "score": 0.35, "rationale": "weak"},
                {"user_id": 2, "wishlist_item_id": 101, "score": 0.88, "rationale": "strong"},
            ]
        }
    )
    result = await call("match_wishlist", {"listing_id": 10})
    ids = [match["wishlist_item_id"] for match in result.structured_content["matches"]]
    assert ids == [101]  # 0.35 is below MATCH_SCORE_THRESHOLD=0.6


async def test_match_wishlist_drops_hallucinated_ids(stub_claude, engine: sa.Engine) -> None:
    """A wishlist id that was not in the prompt must never reach a notification."""
    add_user(engine, 1, "Owner")
    add_user(engine, 2, "Wanter")
    add_listing(engine, 10, owner_id=1)
    add_wishlist(engine, 100, user_id=2, keywords="a study table")

    stub_claude(
        {
            "matches": [
                {"user_id": 2, "wishlist_item_id": 100, "score": 0.9, "rationale": "real"},
                {"user_id": 7, "wishlist_item_id": 999, "score": 0.95, "rationale": "invented"},
                {"user_id": 7, "wishlist_item_id": 100, "score": 0.95, "rationale": "wrong user"},
            ]
        }
    )
    result = await call("match_wishlist", {"listing_id": 10})
    assert [m["wishlist_item_id"] for m in result.structured_content["matches"]] == [100]
    assert [m["user_id"] for m in result.structured_content["matches"]] == [2]


async def test_match_wishlist_reports_a_missing_listing(stub_claude, engine: sa.Engine) -> None:
    stub_claude({"matches": []})
    result = await call("match_wishlist", {"listing_id": 4242})
    assert result.is_error
    assert "4242 was not found" in result.content[0].text


async def test_match_wishlist_db_access_is_read_only(engine: sa.Engine) -> None:
    """The server reads through explicit SELECTs only - nothing it can mutate."""
    import db as db_module

    for statement in (db_module.LISTING_SQL, db_module.WISHLIST_SQL, db_module.CLAIM_SQL):
        sql = str(statement).strip().upper()
        assert sql.startswith("SELECT")
        for verb in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER"):
            assert verb not in sql


# ------------------------------------------------------------------ draft_coordination


async def test_draft_coordination_uses_both_names_and_the_pickup_area(
    stub_claude, engine: sa.Engine
) -> None:
    add_user(engine, 1, "Olivia")
    add_user(engine, 2, "Chris")
    add_listing(engine, 10, owner_id=1, title="Ikea study desk",
                pickup_area="Guy-Concordia metro")
    add_claim(engine, 50, listing_id=10, claimer_id=2, message="Friday works!")

    stub = stub_claude({"message": "Hi Chris, the desk is yours..."})
    result = await call("draft_coordination", {"listing_id": 10, "claim_id": 50})

    assert result.structured_content == {"message": "Hi Chris, the desk is yours..."}
    prompt = stub.last_call["messages"][0]["content"][0]["text"]
    assert "Olivia" in prompt and "Chris" in prompt
    assert "Guy-Concordia metro" in prompt
    assert "Friday works!" in prompt


async def test_draft_coordination_rejects_a_claim_from_another_listing(
    stub_claude, engine: sa.Engine
) -> None:
    add_user(engine, 1, "Olivia")
    add_user(engine, 2, "Chris")
    add_listing(engine, 10, owner_id=1)
    add_listing(engine, 11, owner_id=1, title="Other item")
    add_claim(engine, 50, listing_id=11, claimer_id=2)

    stub_claude({"message": "should not be produced"})
    result = await call("draft_coordination", {"listing_id": 10, "claim_id": 50})
    assert result.is_error
    assert "does not belong to listing" in result.content[0].text


async def test_draft_coordination_reports_a_missing_claim(stub_claude, engine: sa.Engine) -> None:
    add_user(engine, 1, "Olivia")
    add_listing(engine, 10, owner_id=1)
    stub_claude({"message": "x"})
    result = await call("draft_coordination", {"listing_id": 10, "claim_id": 999})
    assert result.is_error
    assert "Claim 999 was not found" in result.content[0].text


# ------------------------------------------------------------------ API failures


async def test_api_error_becomes_a_tool_error_not_a_server_crash(stub_claude) -> None:
    import anthropic
    import httpx2

    error = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com"))
    stub_claude(raises=error)
    result = await call("classify_item", {"title": "Desk", "description": "d"})
    assert result.is_error
    assert "Could not reach the Claude API" in result.content[0].text
    # The session is still usable afterwards.
    async with mcp.Client(build_server()) as client:
        assert len((await client.list_tools()).tools) == 5


async def test_a_refusal_is_reported_as_an_error(stub_claude) -> None:
    stub_claude({"category": "other", "condition_hint": "x"}, stop_reason="refusal")
    result = await call("classify_item", {"title": "x", "description": "y"})
    assert result.is_error
    assert "declined" in result.content[0].text


async def test_malformed_json_is_reported(stub_claude) -> None:
    stub_claude("this is not json")
    result = await call("classify_item", {"title": "x", "description": "y"})
    assert result.is_error
    assert "malformed JSON" in result.content[0].text


async def test_a_missing_api_key_is_a_clean_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import get_settings

    claude.set_client(None)
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")
    result = await call("classify_item", {"title": "x", "description": "y"})
    assert result.is_error
    assert "ANTHROPIC_API_KEY is not configured" in result.content[0].text
