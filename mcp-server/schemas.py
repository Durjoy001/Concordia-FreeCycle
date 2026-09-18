"""JSON-schema fragments shared by the tool definitions.

These literals are the contract between the MCP server, the orchestrator and the
API's enums; they are duplicated here on purpose so the MCP server stays
independent of the FastAPI app's Python package.
"""

from __future__ import annotations

from typing import Any, Final

CATEGORIES: Final[list[str]] = [
    "furniture",
    "books",
    "electronics",
    "kitchen",
    "clothing",
    "other",
]
CONDITIONS: Final[list[str]] = ["like_new", "good", "fair", "worn"]

PROHIBITED_CLASSES: Final[list[str]] = [
    "weapons",
    "alcohol",
    "medications",
    "perishables",
    "counterfeit goods",
    "non-free/sale attempts",
]


def obj(
    properties: dict[str, Any], required: list[str], *, description: str | None = None
) -> dict[str, Any]:
    """A strict object schema: every listed key required, nothing extra allowed."""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
    if description:
        schema["description"] = description
    return schema


STR: Final[dict[str, Any]] = {"type": "string"}
INT: Final[dict[str, Any]] = {"type": "integer"}
BOOL: Final[dict[str, Any]] = {"type": "boolean"}
SCORE: Final[dict[str, Any]] = {"type": "number", "minimum": 0, "maximum": 1}
CATEGORY: Final[dict[str, Any]] = {"type": "string", "enum": CATEGORIES}
CONDITION: Final[dict[str, Any]] = {"type": "string", "enum": CONDITIONS}
