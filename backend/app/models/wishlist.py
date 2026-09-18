from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, pg_enum
from .enums import Category

if TYPE_CHECKING:
    from .user import User


class WishlistItem(Base, TimestampMixin):
    __tablename__ = "wishlist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    keywords: Mapped[str] = mapped_column(sa.String(240), nullable=False)
    category: Mapped[Category | None] = mapped_column(pg_enum(Category, "category"), nullable=True)

    user: Mapped["User"] = relationship(back_populates="wishlist_items")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<WishlistItem id={self.id} keywords={self.keywords!r}>"
