"""/notifications endpoints (polled by the frontend bell every 30s)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.deps import CurrentUser, DbSession
from app.schemas.notification import NotificationList, NotificationRead
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationList)
def list_notifications(
    db: DbSession,
    current_user: CurrentUser,
    unread_only: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NotificationList:
    items, unread = notification_service.list_for_user(
        db, user=current_user, unread_only=unread_only, limit=limit, offset=offset
    )
    return NotificationList(
        items=[NotificationRead.model_validate(item) for item in items],
        unread_count=unread,
    )


@router.patch("/{notification_id}/read", response_model=NotificationRead)
def mark_notification_read(
    notification_id: int, db: DbSession, current_user: CurrentUser
) -> NotificationRead:
    notification = notification_service.mark_read(
        db, user=current_user, notification_id=notification_id
    )
    return NotificationRead.model_validate(notification)
