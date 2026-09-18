"""Fixtures for the MCP server tests.

Everything runs against a real in-process MCP client/server pair and a real SQLite
database; only the Anthropic client is stubbed, so tool dispatch, schemas and SQL
are exercised for real and no API calls are made.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

_TMP_ROOT = Path(tempfile.mkdtemp(prefix="freecycle-mcp-tests-"))
os.environ.update(
    DATABASE_URL=f"sqlite:///{_TMP_ROOT / 'mcp.sqlite3'}",
    UPLOAD_DIR=str(_TMP_ROOT / "uploads"),
    ANTHROPIC_API_KEY="test-key",
    ANTHROPIC_MODEL="claude-sonnet-4-6",
    MATCH_SCORE_THRESHOLD="0.6",
)

import claude  # noqa: E402
import db  # noqa: E402
from config import get_settings  # noqa: E402

TINY_PNG: bytes = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)

SCHEMA_DDL = (
    """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        email VARCHAR(320) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        display_name VARCHAR(80) NOT NULL,
        created_at TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE listings (
        id INTEGER PRIMARY KEY,
        owner_id INTEGER NOT NULL REFERENCES users(id),
        title VARCHAR(140) NOT NULL,
        description TEXT NOT NULL,
        category VARCHAR(20) NOT NULL,
        condition VARCHAR(20) NOT NULL,
        photos TEXT NOT NULL,
        pickup_area VARCHAR(160) NOT NULL,
        status VARCHAR(20) NOT NULL,
        ai_generated BOOLEAN NOT NULL DEFAULT 0,
        flagged BOOLEAN NOT NULL DEFAULT 0,
        flag_reason TEXT,
        created_at TIMESTAMP NOT NULL,
        updated_at TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE claims (
        id INTEGER PRIMARY KEY,
        listing_id INTEGER NOT NULL REFERENCES listings(id),
        claimer_id INTEGER NOT NULL REFERENCES users(id),
        message TEXT NOT NULL,
        status VARCHAR(20) NOT NULL,
        created_at TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE wishlist_items (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        keywords VARCHAR(240) NOT NULL,
        category VARCHAR(20),
        created_at TIMESTAMP NOT NULL
    )
    """,
)


class StubResponse:
    """Mimics the shape of anthropic.types.Message that claude.structured reads."""

    def __init__(self, payload: dict[str, Any] | str, *, stop_reason: str = "end_turn") -> None:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        self.content = [type("TextBlock", (), {"type": "text", "text": text})()]
        self.stop_reason = stop_reason
        self.usage = type("Usage", (), {"input_tokens": 123, "output_tokens": 45})()


class StubMessages:
    def __init__(self, owner: "StubAnthropic") -> None:
        self._owner = owner

    async def create(self, **kwargs: Any) -> StubResponse:
        self._owner.calls.append(kwargs)
        if self._owner.raises is not None:
            raise self._owner.raises
        payload = self._owner.replies.pop(0) if self._owner.replies else {}
        if isinstance(payload, BaseException):
            raise payload
        return StubResponse(payload, stop_reason=self._owner.stop_reason)


class StubAnthropic:
    """A stand-in for anthropic.AsyncAnthropic recording every request."""

    def __init__(self, *replies: Any, raises: BaseException | None = None,
                 stop_reason: str = "end_turn") -> None:
        self.replies: list[Any] = list(replies)
        self.raises = raises
        self.stop_reason = stop_reason
        self.calls: list[dict[str, Any]] = []
        self.messages = StubMessages(self)

    @property
    def last_call(self) -> dict[str, Any]:
        assert self.calls, "no Claude call was made"
        return self.calls[-1]


@pytest.fixture
def stub_claude() -> Generator[Any, None, None]:
    """Factory installing a StubAnthropic as the module-level Claude client."""
    created: list[StubAnthropic] = []

    def _install(*replies: Any, **kwargs: Any) -> StubAnthropic:
        stub = StubAnthropic(*replies, **kwargs)
        claude.set_client(stub)  # type: ignore[arg-type]
        created.append(stub)
        return stub

    yield _install
    claude.set_client(None)


@pytest.fixture
def engine() -> Generator[sa.Engine, None, None]:
    """A fresh SQLite database wired into the MCP server's own connection."""
    path = _TMP_ROOT / "mcp.sqlite3"
    path.unlink(missing_ok=True)
    eng = sa.create_engine(f"sqlite:///{path}", future=True)
    with eng.begin() as connection:
        for statement in SCHEMA_DDL:
            connection.execute(sa.text(statement))
    db.set_engine(eng)
    yield eng
    db.set_engine(None)
    eng.dispose()


@pytest.fixture
def photo() -> str:
    """A real PNG on disk under UPLOAD_DIR; returns its storage key."""
    root = Path(get_settings().upload_dir)
    (root / "listings" / "1").mkdir(parents=True, exist_ok=True)
    key = "listings/1/item.png"
    (root / key).write_bytes(TINY_PNG)
    return key


# ----------------------------------------------------------------- seed helpers


def add_user(engine: sa.Engine, user_id: int, display_name: str, email: str | None = None) -> int:
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO users (id, email, password_hash, display_name, created_at) "
                "VALUES (:id, :email, 'x', :name, '2026-09-18 00:00:00')"
            ),
            {"id": user_id, "email": email or f"user{user_id}@concordia.ca", "name": display_name},
        )
    return user_id


def add_listing(
    engine: sa.Engine,
    listing_id: int,
    owner_id: int,
    *,
    title: str = "Ikea study desk",
    description: str = "White desk, small ink mark.",
    category: str = "furniture",
    condition: str = "good",
    pickup_area: str = "Guy-Concordia metro",
    photos: list[str] | None = None,
) -> int:
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO listings (id, owner_id, title, description, category, condition, "
                "photos, pickup_area, status, ai_generated, flagged, created_at, updated_at) "
                "VALUES (:id, :owner, :title, :description, :category, :condition, :photos, "
                ":pickup, 'available', 0, 0, '2026-09-18 00:00:00', '2026-09-18 00:00:00')"
            ),
            {
                "id": listing_id,
                "owner": owner_id,
                "title": title,
                "description": description,
                "category": category,
                "condition": condition,
                "photos": json.dumps(photos or []),
                "pickup": pickup_area,
            },
        )
    return listing_id


def add_wishlist(
    engine: sa.Engine, item_id: int, user_id: int, keywords: str, category: str | None = None
) -> int:
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO wishlist_items (id, user_id, keywords, category, created_at) "
                "VALUES (:id, :user, :keywords, :category, '2026-09-18 00:00:00')"
            ),
            {"id": item_id, "user": user_id, "keywords": keywords, "category": category},
        )
    return item_id


def add_claim(
    engine: sa.Engine,
    claim_id: int,
    listing_id: int,
    claimer_id: int,
    message: str = "Can I pick it up Friday?",
    status: str = "accepted",
) -> int:
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO claims (id, listing_id, claimer_id, message, status, created_at) "
                "VALUES (:id, :listing, :claimer, :message, :status, '2026-09-18 00:00:00')"
            ),
            {
                "id": claim_id,
                "listing": listing_id,
                "claimer": claimer_id,
                "message": message,
                "status": status,
            },
        )
    return claim_id
