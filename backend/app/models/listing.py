from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, JSONType, TimestampMixin, pg_enum, utcnow
from .enums import Category, Condition, ListingStatus

if TYPE_CHECKING:
    from .claim import Claim
    from .user import User


class Listing(Base, TimestampMixin):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(sa.String(140), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    category: Mapped[Category] = mapped_column(
        pg_enum(Category, "category"), nullable=False, index=True
    )
    condition: Mapped[Condition] = mapped_column(pg_enum(Condition, "condition"), nullable=False)
    # JSONB array of storage-relative photo paths, e.g. ["listings/3/abc.jpg"].
    photos: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    pickup_area: Mapped[str] = mapped_column(sa.String(160), nullable=False, default="")
    status: Mapped[ListingStatus] = mapped_column(
        pg_enum(ListingStatus, "listing_status"),
        nullable=False,
        default=ListingStatus.AVAILABLE,
        index=True,
    )
    ai_generated: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    flagged: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false(), index=True
    )
    flag_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    owner: Mapped["User"] = relationship(back_populates="listings")
    claims: Mapped[list["Claim"]] = relationship(
        back_populates="listing", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Listing id={self.id} title={self.title!r} status={self.status}>"
