"""Listing business logic: creation, querying, mutation, photo handling."""

from __future__ import annotations

from collections.abc import Sequence
from typing import BinaryIO, NamedTuple

import sqlalchemy as sa
from sqlalchemy.orm import Session, selectinload

from app.models import Category, Claim, ClaimStatus, Listing, ListingStatus, User, utcnow
from app.schemas.auth import UserPublic
from app.schemas.listing import ListingCreate, ListingRead, ListingUpdate
from app.services.exceptions import NotFound, PermissionDenied, UnprocessableEntity
from app.services.storage import StorageService, get_storage

MAX_PHOTOS_PER_LISTING = 6


class UploadedPhoto(NamedTuple):
    """A photo handed to the service layer, decoupled from FastAPI's UploadFile."""

    stream: BinaryIO
    content_type: str | None


def _claim_count_subquery() -> sa.ScalarSelect[int]:
    return (
        sa.select(sa.func.count(Claim.id))
        .where(Claim.listing_id == Listing.id, Claim.status == ClaimStatus.PENDING)
        .correlate(Listing)
        .scalar_subquery()
    )


def to_read_model(
    listing: Listing,
    *,
    viewer: User | None = None,
    claim_count: int = 0,
    storage: StorageService | None = None,
) -> ListingRead:
    """Serialise a listing, exposing moderation fields only to its owner."""
    store = storage or get_storage()
    is_owner = viewer is not None and viewer.id == listing.owner_id
    return ListingRead(
        id=listing.id,
        owner=UserPublic.model_validate(listing.owner),
        title=listing.title,
        description=listing.description,
        category=listing.category,
        condition=listing.condition,
        photos=[store.public_url(key) for key in (listing.photos or [])],
        pickup_area=listing.pickup_area,
        status=listing.status,
        ai_generated=listing.ai_generated,
        created_at=listing.created_at,
        updated_at=listing.updated_at,
        claim_count=claim_count,
        is_owner=is_owner,
        flagged=listing.flagged if is_owner else None,
        flag_reason=listing.flag_reason if is_owner else None,
    )


def get_listing(db: Session, listing_id: int) -> Listing:
    stmt = (
        sa.select(Listing)
        .options(selectinload(Listing.owner))
        .where(Listing.id == listing_id)
    )
    listing = db.execute(stmt).scalar_one_or_none()
    if listing is None:
        raise NotFound("Listing not found.")
    return listing


def get_visible_listing(db: Session, listing_id: int, viewer: User | None) -> Listing:
    """Fetch a listing, hiding removed/flagged ones from everyone but the owner."""
    listing = get_listing(db, listing_id)
    is_owner = viewer is not None and viewer.id == listing.owner_id
    if not is_owner and (listing.flagged or listing.status == ListingStatus.REMOVED):
        # 404 rather than 403: a hidden listing should not confirm it exists.
        raise NotFound("Listing not found.")
    return listing


def require_owner(listing: Listing, user: User) -> Listing:
    if listing.owner_id != user.id:
        raise PermissionDenied("Only the owner can modify this listing.")
    return listing


def list_listings(
    db: Session,
    *,
    viewer: User | None = None,
    category: Category | None = None,
    status: ListingStatus | None = None,
    search: str | None = None,
    mine: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[tuple[Listing, int]], int]:
    """Return ((listing, pending_claim_count), ...) plus the unpaginated total."""
    conditions: list[sa.ColumnElement[bool]] = []

    if mine:
        if viewer is None:
            raise PermissionDenied("Authentication required to list your own listings.")
        conditions.append(Listing.owner_id == viewer.id)
    else:
        # Flagged listings are invisible to everyone but their owner.
        visible = sa.and_(Listing.flagged.is_(False), Listing.status != ListingStatus.REMOVED)
        if viewer is not None:
            conditions.append(sa.or_(visible, Listing.owner_id == viewer.id))
        else:
            conditions.append(visible)

    if category is not None:
        conditions.append(Listing.category == category)
    if status is not None:
        conditions.append(Listing.status == status)
    elif not mine:
        # Default browse view: only things still up for grabs.
        conditions.append(Listing.status.in_([ListingStatus.AVAILABLE, ListingStatus.CLAIMED]))

    if search:
        needle = f"%{search.strip().lower()}%"
        conditions.append(
            sa.or_(
                sa.func.lower(Listing.title).like(needle),
                sa.func.lower(Listing.description).like(needle),
                sa.func.lower(Listing.pickup_area).like(needle),
            )
        )

    where = sa.and_(*conditions) if conditions else sa.true()

    total = db.execute(sa.select(sa.func.count(Listing.id)).where(where)).scalar_one()

    stmt = (
        sa.select(Listing, _claim_count_subquery().label("claim_count"))
        .options(selectinload(Listing.owner))
        .where(where)
        .order_by(Listing.created_at.desc(), Listing.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = [(row[0], int(row[1] or 0)) for row in db.execute(stmt).all()]
    return rows, int(total)


def _save_photos(
    store: StorageService, listing_id: int, photos: Sequence[UploadedPhoto]
) -> list[str]:
    keys: list[str] = []
    try:
        for photo in photos:
            keys.append(
                store.save(
                    photo.stream, prefix=f"listings/{listing_id}", content_type=photo.content_type
                )
            )
    except Exception:
        # Never leave orphaned blobs behind if one photo of several is rejected.
        for key in keys:
            store.delete(key)
        raise
    return keys


def adopt_draft_keys(store: StorageService, owner: User, keys: Sequence[str]) -> list[str]:
    """Validate storage keys produced earlier by POST /agent/draft-listing.

    The key is namespaced by user id at write time, so checking the prefix here
    stops one student from attaching another student's uploaded photo.
    """
    expected_prefix = f"drafts/{owner.id}/"
    adopted: list[str] = []
    for key in keys:
        if not key.startswith(expected_prefix) or not store.exists(key):
            raise UnprocessableEntity(f"Unknown draft photo {key!r}.")
        adopted.append(key)
    return adopted


def create_listing(
    db: Session,
    *,
    owner: User,
    payload: ListingCreate,
    photos: Sequence[UploadedPhoto] = (),
    draft_photo_keys: Sequence[str] = (),
    storage: StorageService | None = None,
) -> Listing:
    store = storage or get_storage()
    adopted = adopt_draft_keys(store, owner, draft_photo_keys)
    if len(photos) + len(adopted) > MAX_PHOTOS_PER_LISTING:
        raise UnprocessableEntity(f"At most {MAX_PHOTOS_PER_LISTING} photos per listing.")

    listing = Listing(
        owner_id=owner.id,
        title=payload.title,
        description=payload.description,
        category=payload.category,
        condition=payload.condition,
        pickup_area=payload.pickup_area,
        ai_generated=payload.ai_generated,
        photos=[],
        status=ListingStatus.AVAILABLE,
    )
    db.add(listing)
    db.flush()  # assign listing.id so new photo keys can be namespaced by it

    try:
        saved = _save_photos(store, listing.id, photos)
    except Exception:
        db.rollback()
        raise

    # Adopted draft keys keep their original path; the key is opaque to callers.
    listing.photos = adopted + saved
    db.commit()
    db.refresh(listing)
    return listing


def update_listing(db: Session, *, listing: Listing, payload: ListingUpdate) -> Listing:
    changes = payload.model_dump(exclude_unset=True)

    if "status" in changes and changes["status"] is not None:
        _validate_status_transition(db, listing, ListingStatus(changes["status"]))

    for field, value in changes.items():
        if value is not None:
            setattr(listing, field, value)

    listing.updated_at = utcnow()
    db.commit()
    db.refresh(listing)
    return listing


def _validate_status_transition(db: Session, listing: Listing, new_status: ListingStatus) -> None:
    """Owners may retract or complete a listing, but must not fake a claim."""
    if new_status == listing.status:
        return
    if new_status == ListingStatus.CLAIMED:
        raise UnprocessableEntity(
            "A listing becomes 'claimed' by accepting a claim, not by editing it."
        )
    if new_status == ListingStatus.COMPLETED:
        accepted = db.execute(
            sa.select(sa.func.count(Claim.id)).where(
                Claim.listing_id == listing.id, Claim.status == ClaimStatus.ACCEPTED
            )
        ).scalar_one()
        if not accepted:
            raise UnprocessableEntity("Accept a claim before marking the listing completed.")


def delete_listing(db: Session, *, listing: Listing) -> None:
    """Soft delete: the row and its claim history survive, the listing disappears."""
    listing.status = ListingStatus.REMOVED
    listing.updated_at = utcnow()
    db.commit()


def apply_moderation(
    db: Session, *, listing_id: int, flagged: bool, reason: str | None
) -> Listing | None:
    """Record a moderation verdict from the agent layer. Returns None if gone."""
    listing = db.get(Listing, listing_id)
    if listing is None:
        return None
    listing.flagged = flagged
    listing.flag_reason = reason if flagged else None
    listing.updated_at = utcnow()
    db.commit()
    db.refresh(listing)
    return listing
