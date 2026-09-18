from __future__ import annotations

from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, JSONType, TimestampMixin, pg_enum
from .enums import NotificationType

if TYPE_CHECKING:
    from .user import User


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"
    __table_args__ = (sa.Index("ix_notifications_user_read", "user_id", "read"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[NotificationType] = mapped_column(
        pg_enum(NotificationType, "notification_type"), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    read: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )

    user: Mapped["User"] = relationship(back_populates="notifications")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Notification id={self.id} type={self.type} read={self.read}>"
