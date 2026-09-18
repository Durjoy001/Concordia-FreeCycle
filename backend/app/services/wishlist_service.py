"""Wishlist business logic."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models import User, WishlistItem
from app.schemas.wishlist import WishlistItemCreate
from app.services.exceptions import Conflict, NotFound

MAX_WISHLIST_ITEMS = 25


def list_items(db: Session, *, user: User) -> list[WishlistItem]:
    stmt = (
        sa.select(WishlistItem)
        .where(WishlistItem.user_id == user.id)
        .order_by(WishlistItem.created_at.desc(), WishlistItem.id.desc())
    )
    return list(db.execute(stmt).scalars().all())


def create_item(db: Session, *, user: User, payload: WishlistItemCreate) -> WishlistItem:
    existing = list_items(db, user=user)
    if len(existing) >= MAX_WISHLIST_ITEMS:
        raise Conflict(f"A wishlist holds at most {MAX_WISHLIST_ITEMS} items.")

    normalized = payload.keywords.casefold()
    for item in existing:
        if item.keywords.casefold() == normalized and item.category == payload.category:
            raise Conflict("That wishlist entry already exists.")

    item = WishlistItem(user_id=user.id, keywords=payload.keywords, category=payload.category)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def delete_item(db: Session, *, user: User, item_id: int) -> None:
    item = db.get(WishlistItem, item_id)
    # A wishlist entry belonging to somebody else is simply not found, so the
    # endpoint cannot be used to probe for other users' rows.
    if item is None or item.user_id != user.id:
        raise NotFound("Wishlist item not found.")
    db.delete(item)
    db.commit()
