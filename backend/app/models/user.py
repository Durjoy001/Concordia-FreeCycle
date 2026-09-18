from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .claim import Claim
    from .listing import Listing
    from .notification import Notification
    from .wishlist import WishlistItem


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(sa.String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(sa.String(80), nullable=False)

    listings: Mapped[list["Listing"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    claims: Mapped[list["Claim"]] = relationship(
        back_populates="claimer", cascade="all, delete-orphan"
    )
    wishlist_items: Mapped[list["WishlistItem"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User id={self.id} email={self.email!r}>"
