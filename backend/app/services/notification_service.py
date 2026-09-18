"""Notification creation and reads.

Every write goes through `create` so the payload shape per type stays in one place;
the agent layer and the claims flow both call in here rather than inserting rows.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models import Claim, Listing, Notification, NotificationType, User
from app.services.exceptions import NotFound


def create(
    db: Session,
    *,
    user_id: int,
    notification_type: NotificationType,
    payload: dict[str, Any],
    commit: bool = True,
) -> Notification:
    notification = Notification(
        user_id=user_id, type=notification_type, payload=payload, read=False
    )
    db.add(notification)
    if commit:
        db.commit()
        db.refresh(notification)
    else:
        db.flush()
    return notification


def notify_claim_received(db: Session, *, listing: Listing, claim: Claim, claimer: User) -> None:
    create(
        db,
        user_id=listing.owner_id,
        notification_type=NotificationType.CLAIM_RECEIVED,
        payload={
            "listing_id": listing.id,
            "listing_title": listing.title,
            "claim_id": claim.id,
            "claimer_display_name": claimer.display_name,
            "message": claim.message,
        },
    )


def notify_claim_accepted(db: Session, *, listing: Listing, claim: Claim, owner: User) -> None:
    create(
        db,
        user_id=claim.claimer_id,
        notification_type=NotificationType.CLAIM_ACCEPTED,
        payload={
            "listing_id": listing.id,
            "listing_title": listing.title,
            "claim_id": claim.id,
            "owner_display_name": owner.display_name,
            "pickup_area": listing.pickup_area,
        },
    )


def notify_wishlist_match(
    db: Session,
    *,
    user_id: int,
    listing: Listing,
    wishlist_item_id: int,
    score: float,
    rationale: str,
    commit: bool = True,
) -> Notification:
    """Raised by the matching agent, not by a user action."""
    return create(
        db,
        user_id=user_id,
        notification_type=NotificationType.WISHLIST_MATCH,
        payload={
            "listing_id": listing.id,
            "listing_title": listing.title,
            "listing_category": listing.category.value,
            "wishlist_item_id": wishlist_item_id,
            "score": round(float(score), 3),
            "rationale": rationale,
        },
        commit=commit,
    )


def list_for_user(
    db: Session, *, user: User, unread_only: bool = False, limit: int = 50, offset: int = 0
) -> tuple[list[Notification], int]:
    """Returns (page of notifications, total unread count)."""
    conditions = [Notification.user_id == user.id]
    if unread_only:
        conditions.append(Notification.read.is_(False))

    stmt = (
        sa.select(Notification)
        .where(sa.and_(*conditions))
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
        .offset(offset)
    )
    items = list(db.execute(stmt).scalars().all())

    unread = db.execute(
        sa.select(sa.func.count(Notification.id)).where(
            Notification.user_id == user.id, Notification.read.is_(False)
        )
    ).scalar_one()
    return items, int(unread)


def mark_read(db: Session, *, user: User, notification_id: int) -> Notification:
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise NotFound("Notification not found.")
    if not notification.read:
        notification.read = True
        db.commit()
        db.refresh(notification)
    return notification
