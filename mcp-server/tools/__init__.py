"""The five FreeCycle MCP tools.

Each module exposes NAME, DESCRIPTION, INPUT_SCHEMA, OUTPUT_SCHEMA and an async
`run(arguments) -> dict`, so server.py can register them uniformly.
"""

from . import (
    classify_item,
    create_listing_from_photo,
    draft_coordination,
    flag_prohibited,
    match_wishlist,
)

TOOL_MODULES = (
    create_listing_from_photo,
    classify_item,
    flag_prohibited,
    match_wishlist,
    draft_coordination,
)

__all__ = ["TOOL_MODULES"]
