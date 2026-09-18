"""Read-only database access for the MCP server.

The server holds its *own* engine and never imports the FastAPI app's models: it
reads through explicit SQL so the tool layer cannot accidentally mutate anything.
Every statement goes through `_read` on a connection opened for that call.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy import Engine, create_engine

from config import get_settings

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = get_settings().database_url
        connect_args: dict[str, Any] = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(url, pool_pre_ping=True, future=True, connect_args=connect_args)
    return _engine


def set_engine(engine: Engine | None) -> None:
    """Point the server at a different database (used by the test suite)."""
    global _engine
    _engine = engine


def _read(statement: sa.TextClause, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run a read-only statement inside a transaction that is always rolled back."""
    with get_engine().connect() as connection:
        rows = connection.execute(statement, params or {}).mappings().all()
        connection.rollback()
    return [dict(row) for row in rows]


LISTING_SQL = sa.text(
    """
    SELECT l.id,
           l.owner_id,
           l.title,
           l.description,
           l.category,
           l.condition,
           l.photos,
           l.pickup_area,
           l.status,
           u.display_name AS owner_display_name
      FROM listings l
      JOIN users u ON u.id = l.owner_id
     WHERE l.id = :listing_id
    """
)

WISHLIST_SQL = sa.text(
    """
    SELECT w.id AS wishlist_item_id,
           w.user_id,
           w.keywords,
           w.category,
           u.display_name
      FROM wishlist_items w
      JOIN users u ON u.id = w.user_id
     WHERE w.user_id <> :owner_id
     ORDER BY w.id
     LIMIT :limit
    """
)

CLAIM_SQL = sa.text(
    """
    SELECT c.id,
           c.listing_id,
           c.claimer_id,
           c.message,
           c.status,
           u.display_name AS claimer_display_name
      FROM claims c
      JOIN users u ON u.id = c.claimer_id
     WHERE c.id = :claim_id
    """
)


def fetch_listing(listing_id: int) -> dict[str, Any] | None:
    rows = _read(LISTING_SQL, {"listing_id": listing_id})
    return rows[0] if rows else None


def fetch_wishlist_candidates(owner_id: int, limit: int | None = None) -> list[dict[str, Any]]:
    """Every wishlist entry except the listing owner's own."""
    cap = limit if limit is not None else get_settings().max_wishlist_candidates
    return _read(WISHLIST_SQL, {"owner_id": owner_id, "limit": cap})


def fetch_claim(claim_id: int) -> dict[str, Any] | None:
    rows = _read(CLAIM_SQL, {"claim_id": claim_id})
    return rows[0] if rows else None
