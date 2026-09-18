"""Declarative base and shared column types."""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Real JSONB on PostgreSQL; plain JSON elsewhere so the test suite can run on SQLite.
JSONType = sa.JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    """Timezone-aware UTC now (SQLite has no native tz support, so we normalise here)."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )


def pg_enum(enum_cls: type, name: str) -> sa.Enum:
    """Native PostgreSQL enum storing the member *values* (not the member names)."""
    return sa.Enum(
        enum_cls,
        name=name,
        native_enum=True,
        values_callable=lambda cls: [member.value for member in cls],
    )
