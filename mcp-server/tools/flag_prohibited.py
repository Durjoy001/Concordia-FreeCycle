"""flag_prohibited - moderation gate for listings."""

from __future__ import annotations

from typing import Any, Final

import claude
import schemas

NAME: Final = "flag_prohibited"
DESCRIPTION: Final = (
    "Check whether a listing breaks FreeCycle's rules: weapons, alcohol, medications, "
    "perishable food, counterfeit goods, or an attempt to sell rather than give away. "
    "Pass the photo as well when there is one - the image can contradict the text. "
    "Returns flagged=true with a reason when the listing must be hidden from other students."
)

INPUT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "photo_path": {
            "type": ["string", "null"],
            "description": "Storage key of the listing photo, or null when there is none.",
        },
        "title": {**schemas.STR, "maxLength": 140},
        "description": {**schemas.STR, "maxLength": 4000},
    },
    "required": ["photo_path", "title", "description"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "flagged": {**schemas.BOOL, "description": "True when the listing must be hidden."},
        "reason": {
            "type": ["string", "null"],
            "maxLength": 300,
            "description": (
                "One short sentence the owner will read, naming the rule broken. "
                "Null when flagged is false."
            ),
        },
    },
    "required": ["flagged", "reason"],
    "additionalProperties": False,
}

SYSTEM: Final = """You moderate a Concordia University student exchange where items are given \
away free. Decide whether a listing must be hidden.

Flag it when the item is, or the text offers:
- weapons: firearms, ammunition, knives presented as weapons, tasers, pepper spray
- alcohol: any alcoholic drink, including unopened bottles
- medications: prescription or over-the-counter drugs, supplements, vitamins, cannabis
- perishables: fresh or cooked food, opened food, anything needing refrigeration
- counterfeit goods: replica or knock-off branded items, pirated media, cracked software
- non-free/sale attempts: a price, "obo", "best offer", "trade for", "swap", "$", "e-transfer", \
"Venmo", or any request for money or barter

Do NOT flag ordinary student items: kitchen knives and cookware presented as kitchenware, \
sealed non-perishable pantry food, empty bottles or glassware, textbooks, electronics, \
furniture, clothing, or a listing that merely mentions what the item originally cost while \
still giving it away free.

Read the photo, if given, against the text - a listing titled "free textbooks" showing a bottle \
of vodka is flagged. When flagged, write one plain sentence the owner will read, naming which \
rule was broken. When nothing is wrong, set flagged to false and reason to null. Borderline \
cases are not flagged; a wrongly hidden listing costs a student their giveaway."""


async def run(arguments: dict[str, Any]) -> dict[str, Any]:
    photo_path = arguments.get("photo_path")
    title = str(arguments.get("title") or "")
    description = str(arguments.get("description") or "")

    content: list[dict[str, Any]] = []
    if photo_path:
        content.append(claude.image_block(str(photo_path)))
    content.append(
        {
            "type": "text",
            "text": (
                f"Listing title: {title}\n\n"
                f"Listing description: {description or '(none provided)'}\n\n"
                "Decide whether this listing must be hidden."
            ),
        }
    )
    result = await claude.structured(
        system=SYSTEM, content=content, schema=OUTPUT_SCHEMA, max_tokens=1024
    )
    # Defend the invariant the API relies on: a reason without a flag, or a flag
    # without a reason, would produce a confusing owner notice.
    if not result.get("flagged"):
        result["reason"] = None
    elif not result.get("reason"):
        result["reason"] = "This listing appears to break FreeCycle's prohibited-items rules."
    return result
