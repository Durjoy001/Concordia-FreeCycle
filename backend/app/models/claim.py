from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, pg_enum
from .enums import ClaimStatus

if TYPE_CHECKING:
    from .listing import Listing
    from .user import User


class Claim(Base, TimestampMixin):
    __tablename__ = "claims"
    __table_args__ = (
        # A student may only have one open claim per listing.
        sa.UniqueConstraint("listing_id", "claimer_id", name="uq_claim_listing_claimer"),
        sa.Index("ix_claims_listing_status", "listing_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        sa.ForeignKey("listings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    claimer_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    status: Mapped[ClaimStatus] = mapped_column(
        pg_enum(ClaimStatus, "claim_status"), nullable=False, default=ClaimStatus.PENDING
    )
    # The pickup message the agent drafted when this claim was accepted. Stored so both
    # parties still see it after a reload, and so it is never re-drafted (and re-billed).
    drafted_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    listing: Mapped["Listing"] = relationship(back_populates="claims")
    claimer: Mapped["User"] = relationship(back_populates="claims")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Claim id={self.id} listing_id={self.listing_id} status={self.status}>"
