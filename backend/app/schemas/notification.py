"""Notification schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import NotificationType


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: NotificationType
    payload: dict[str, Any]
    read: bool
    created_at: datetime


class NotificationList(BaseModel):
    """Bell-friendly envelope: the list plus the badge number."""

    items: list[NotificationRead]
    unread_count: int
