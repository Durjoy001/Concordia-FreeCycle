"""classify_item - text-only categorisation for hand-written listings."""

from __future__ import annotations

from typing import Any, Final

import claude
import schemas

NAME: Final = "classify_item"
DESCRIPTION: Final = (
    "Read a listing's title and description and decide which category it belongs to, plus a "
    "short hint about the condition the text implies. Use this for listings a student wrote "
    "by hand, or to sanity-check a category the student picked. No photo required."
)

INPUT_SCHEMA: Final[dict[str, Any]] = schemas.obj(
    {
        "title": {**schemas.STR, "maxLength": 140, "description": "The listing title."},
        "description": {
            **schemas.STR,
            "maxLength": 4000,
            "description": "The listing description; may be empty.",
        },
    },
    ["title", "description"],
)

OUTPUT_SCHEMA: Final[dict[str, Any]] = schemas.obj(
    {
        "category": schemas.CATEGORY,
        "condition_hint": {
            **schemas.STR,
            "maxLength": 200,
            "description": (
                "One sentence on the condition the text implies, or a note that the text "
                "does not say."
            ),
        },
    },
    ["category", "condition_hint"],
)

SYSTEM: Final = """You categorise giveaway listings for a student free-item exchange.

Pick the single best category from the allowed list. Guidance on the boundaries:
- furniture: desks, chairs, shelves, beds, lamps, storage
- books: textbooks, novels, course notes, manuals
- electronics: computers, phones, monitors, cables, chargers, audio gear
- kitchen: cookware, small appliances, dishes, cutlery, food storage
- clothing: clothes, shoes, bags, outerwear
- other: anything that does not clearly fit above (sports gear, plants, art supplies, decor)

For condition_hint, report only what the text states or strongly implies - quote the telling \
phrase where there is one. If the text says nothing about condition, say so plainly rather \
than guessing."""


async def run(arguments: dict[str, Any]) -> dict[str, Any]:
    title = str(arguments["title"])
    description = str(arguments.get("description") or "")
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": f"Title: {title}\n\nDescription: {description or '(none provided)'}",
        }
    ]
    return await claude.structured(
        system=SYSTEM, content=content, schema=OUTPUT_SCHEMA, max_tokens=1024
    )
