"""draft_coordination - friendly pickup message for an accepted claim."""

from __future__ import annotations

from typing import Any, Final

import claude
import db
import schemas
from claude import ToolError

NAME: Final = "draft_coordination"
DESCRIPTION: Final = (
    "Write the message the item's owner can send to the student whose claim they just accepted, "
    "arranging the handover. Uses both students' display names and the listing's pickup area. "
    "Reads the listing and the claim from the database - pass only their ids."
)

INPUT_SCHEMA: Final[dict[str, Any]] = schemas.obj(
    {
        "listing_id": {**schemas.INT, "minimum": 1},
        "claim_id": {**schemas.INT, "minimum": 1},
    },
    ["listing_id", "claim_id"],
)

OUTPUT_SCHEMA: Final[dict[str, Any]] = schemas.obj(
    {
        "message": {
            **schemas.STR,
            "maxLength": 900,
            "description": "The ready-to-send message, addressed to the claimer.",
        }
    },
    ["message"],
)

SYSTEM: Final = """You write the short message a Concordia student sends after agreeing to hand \
over a free item.

Write as the owner, addressing the claimer by name. Cover, in 3-5 sentences:
- confirmation that the item is theirs
- the pickup area, named exactly as the listing gives it
- a concrete proposal for arranging a time, asking what suits them
- one practical note where it earns its place (bring a bag for a box of books; it is heavy and \
awkward for one person to carry; it does not fit in a backpack)

Sign off with the owner's display name. Warm and plain - a student texting another student, not \
a customer-service reply. Never invent a specific date, time, phone number, room number or \
street address: the owner has not told you any of those. Do not add a subject line, a greeting \
placeholder like [Name], or any commentary outside the message itself."""


async def run(arguments: dict[str, Any]) -> dict[str, Any]:
    listing_id = int(arguments["listing_id"])
    claim_id = int(arguments["claim_id"])

    listing = db.fetch_listing(listing_id)
    if listing is None:
        raise ToolError(f"Listing {listing_id} was not found.")
    claim = db.fetch_claim(claim_id)
    if claim is None:
        raise ToolError(f"Claim {claim_id} was not found.")
    if int(claim["listing_id"]) != listing_id:
        raise ToolError(f"Claim {claim_id} does not belong to listing {listing_id}.")

    prompt = (
        f"Owner (you): {listing['owner_display_name']}\n"
        f"Claimer: {claim['claimer_display_name']}\n"
        f"Item: {listing['title']}\n"
        f"Item description: {listing['description'] or '(none)'}\n"
        f"Pickup area: {listing['pickup_area']}\n"
        f"Message the claimer sent: {claim['message'] or '(none)'}\n\n"
        "Write the pickup message."
    )
    return await claude.structured(
        system=SYSTEM,
        content=[{"type": "text", "text": prompt}],
        schema=OUTPUT_SCHEMA,
        max_tokens=1024,
    )
