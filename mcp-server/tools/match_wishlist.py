"""match_wishlist - semantic pairing of a new listing against student wishlists."""

from __future__ import annotations

import json
from typing import Any, Final

import claude
import db
import schemas
from claude import ToolError
from config import get_settings

NAME: Final = "match_wishlist"
DESCRIPTION: Final = (
    "Score a listing against every other student's wishlist entries and return the ones that "
    "genuinely match, with a score and a one-line rationale. Matching is semantic, not keyword "
    "based: 'study desk' matches a wishlist entry for 'table for studying'. Reads the listing "
    "and the wishlists from the database itself - pass only the listing id."
)

INPUT_SCHEMA: Final[dict[str, Any]] = schemas.obj(
    {"listing_id": {**schemas.INT, "minimum": 1, "description": "Id of the listing to match."}},
    ["listing_id"],
)

MATCH_SCHEMA: Final[dict[str, Any]] = schemas.obj(
    {
        "user_id": {**schemas.INT, "description": "Owner of the matched wishlist entry."},
        "wishlist_item_id": {**schemas.INT, "description": "The matched wishlist entry."},
        "score": {**schemas.SCORE, "description": "0..1 semantic relevance."},
        "rationale": {
            **schemas.STR,
            "maxLength": 240,
            "description": "One sentence explaining the match to the student.",
        },
    },
    ["user_id", "wishlist_item_id", "score", "rationale"],
)

OUTPUT_SCHEMA: Final[dict[str, Any]] = schemas.obj(
    {"matches": {"type": "array", "items": MATCH_SCHEMA, "maxItems": 25}},
    ["matches"],
)

SYSTEM: Final = """You match a newly posted free item against students' wishlists.

You are given one listing and a numbered list of wishlist entries belonging to other students. \
Score how well the listing satisfies each entry, from 0 to 1:
- 0.9-1.0: the entry asks for exactly this item
- 0.7-0.9: a different wording for the same need ("study desk" vs "table for studying", \
"kettle" vs "something to boil water")
- 0.5-0.7: same purpose, imperfect fit (a bar stool for someone wanting a desk chair)
- below 0.5: same category but a different need (a novel for someone wanting a calculus \
textbook) - these should not be returned

Judge the *need*, not the words: matching on a shared word alone is a mistake ("desk lamp" does \
not satisfy "desk"). A wishlist category, when set, is a hint and not a requirement.

Return only entries you would be glad to notify the student about, at most 10, each with a \
one-sentence rationale naming the wishlist wording and the item. Every wishlist_item_id and \
user_id must be copied exactly from the input. If nothing matches, return an empty array - that \
is a normal and useful answer."""


def _candidate_lines(candidates: list[dict[str, Any]]) -> str:
    return "\n".join(
        "- wishlist_item_id={wishlist_item_id} user_id={user_id} "
        'keywords="{keywords}" category={category}'.format(
            wishlist_item_id=row["wishlist_item_id"],
            user_id=row["user_id"],
            keywords=row["keywords"],
            category=row["category"] or "(any)",
        )
        for row in candidates
    )


def _photos(listing: dict[str, Any]) -> list[str]:
    photos = listing.get("photos")
    if isinstance(photos, str):  # SQLite returns JSON columns as text
        try:
            photos = json.loads(photos)
        except json.JSONDecodeError:
            return []
    return [str(photo) for photo in photos] if isinstance(photos, list) else []


async def run(arguments: dict[str, Any]) -> dict[str, Any]:
    listing_id = int(arguments["listing_id"])
    listing = db.fetch_listing(listing_id)
    if listing is None:
        raise ToolError(f"Listing {listing_id} was not found.")

    candidates = db.fetch_wishlist_candidates(int(listing["owner_id"]))
    if not candidates:
        # No Claude call needed, and no tokens spent, when nobody is waiting for anything.
        return {"matches": [], "_usage": {"input_tokens": 0, "output_tokens": 0}}

    prompt = (
        "Listing:\n"
        f"  title: {listing['title']}\n"
        f"  description: {listing['description'] or '(none)'}\n"
        f"  category: {listing['category']}\n"
        f"  condition: {listing['condition']}\n"
        f"  pickup_area: {listing['pickup_area']}\n\n"
        f"Wishlist entries ({len(candidates)}):\n{_candidate_lines(candidates)}\n\n"
        "Return the entries this listing genuinely satisfies."
    )
    result = await claude.structured(
        system=SYSTEM,
        content=[{"type": "text", "text": prompt}],
        schema=OUTPUT_SCHEMA,
        max_tokens=2048,
    )

    # Drop anything below threshold, and anything whose ids Claude did not copy from
    # the input - a hallucinated user_id would notify the wrong student.
    valid = {(row["wishlist_item_id"], row["user_id"]) for row in candidates}
    threshold = get_settings().match_score_threshold
    result["matches"] = [
        match
        for match in result.get("matches", [])
        if (match.get("wishlist_item_id"), match.get("user_id")) in valid
        and float(match.get("score", 0)) >= threshold
    ]
    return result
