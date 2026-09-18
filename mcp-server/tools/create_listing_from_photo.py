"""create_listing_from_photo - vision-drafted listing fields."""

from __future__ import annotations

from typing import Any, Final

import claude
import schemas

NAME: Final = "create_listing_from_photo"
DESCRIPTION: Final = (
    "Look at a photo of a free item and draft listing fields for it: a short title, "
    "a factual description, the best-fitting category and an apparent condition. "
    "Use this when the student uploaded a photo and wants the form filled in for them. "
    "Returns a confidence score reflecting how clearly the item is identifiable."
)

INPUT_SCHEMA: Final[dict[str, Any]] = schemas.obj(
    {
        "photo_path": {
            **schemas.STR,
            "description": "Storage key of an uploaded photo, e.g. 'drafts/4/ab12.jpg'.",
        }
    },
    ["photo_path"],
)

OUTPUT_SCHEMA: Final[dict[str, Any]] = schemas.obj(
    {
        "title": {**schemas.STR, "maxLength": 140, "description": "Short item title."},
        "description": {
            **schemas.STR,
            "maxLength": 1200,
            "description": "Two or three factual sentences, including visible wear.",
        },
        "category": schemas.CATEGORY,
        "condition": schemas.CONDITION,
        "confidence": {
            **schemas.SCORE,
            "description": "0..1 - how confident the identification is.",
        },
    },
    ["title", "description", "category", "condition", "confidence"],
)

SYSTEM: Final = """You draft giveaway listings for Concordia University's FreeCycle, \
where students hand on items they no longer need for free.

Look only at what the photo actually shows. Write:
- title: 3-8 words naming the item plainly ("Ikea Malm desk", not "Great desk!!"). No prices, \
no emoji, no marketing language.
- description: 2-3 factual sentences. Name the item, its material/colour/approximate size, and \
any damage or wear you can see. Mention what is NOT visible if it matters (e.g. "cables not \
pictured"). Never invent a brand, a model number, a measurement or a history you cannot see.
- category: the single best fit from the allowed list.
- condition: like_new (no visible wear), good (light wear), fair (clear wear, fully usable), \
worn (damaged but still has use).
- confidence: your confidence that the item is correctly identified. Use 0.9+ only when the \
item is unmistakable, 0.4-0.7 when the photo is dark, cluttered or partial, and below 0.3 when \
you are essentially guessing.

A student will review and edit these fields before anything is published, so an honest low \
confidence is more useful than a confident guess."""


async def run(arguments: dict[str, Any]) -> dict[str, Any]:
    photo_path = str(arguments["photo_path"])
    content: list[dict[str, Any]] = [
        claude.image_block(photo_path),
        {
            "type": "text",
            "text": "Draft the listing fields for this item using the required JSON schema.",
        },
    ]
    return await claude.structured(system=SYSTEM, content=content, schema=OUTPUT_SCHEMA)
