"""/wishlist endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.core.deps import CurrentUser, DbSession
from app.schemas.wishlist import WishlistItemCreate, WishlistItemRead
from app.services import wishlist_service

router = APIRouter(prefix="/wishlist", tags=["wishlist"])


@router.get("", response_model=list[WishlistItemRead])
def list_wishlist(db: DbSession, current_user: CurrentUser) -> list[WishlistItemRead]:
    items = wishlist_service.list_items(db, user=current_user)
    return [WishlistItemRead.model_validate(item) for item in items]


@router.post("", response_model=WishlistItemRead, status_code=status.HTTP_201_CREATED)
def add_wishlist_item(
    payload: WishlistItemCreate, db: DbSession, current_user: CurrentUser
) -> WishlistItemRead:
    item = wishlist_service.create_item(db, user=current_user, payload=payload)
    return WishlistItemRead.model_validate(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_wishlist_item(item_id: int, db: DbSession, current_user: CurrentUser) -> Response:
    wishlist_service.delete_item(db, user=current_user, item_id=item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
