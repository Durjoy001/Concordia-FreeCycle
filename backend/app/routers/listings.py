"""/listings endpoints."""

from __future__ import annotations

from typing import Annotated

import sqlalchemy as sa
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Query,
    Response,
    UploadFile,
    status,
)

from app.core.deps import CurrentUser, DbSession
from app.core.forms import validate_form
from app.core.optional_auth import OptionalUser
from app.models import Claim, ClaimStatus
from app.models.enums import Category, Condition, ListingStatus
from app.schemas.listing import ListingCreate, ListingRead, ListingUpdate, Page
from app.services import agent_service, listing_service
from app.services.listing_service import UploadedPhoto

router = APIRouter(prefix="/listings", tags=["listings"])


def _to_uploaded(photos: list[UploadFile]) -> list[UploadedPhoto]:
    """Adapt FastAPI's UploadFile to the storage-agnostic service input."""
    return [
        UploadedPhoto(stream=photo.file, content_type=photo.content_type)
        for photo in photos
        if photo is not None and photo.filename
    ]


@router.get("", response_model=Page[ListingRead])
def browse_listings(
    db: DbSession,
    viewer: OptionalUser,
    category: Annotated[Category | None, Query()] = None,
    status_filter: Annotated[ListingStatus | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query(max_length=120)] = None,
    mine: Annotated[bool, Query(description="Only the caller's own listings.")] = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ListingRead]:
    rows, total = listing_service.list_listings(
        db,
        viewer=viewer,
        category=category,
        status=status_filter,
        search=search,
        mine=mine,
        limit=limit,
        offset=offset,
    )
    return Page[ListingRead](
        items=[
            listing_service.to_read_model(listing, viewer=viewer, claim_count=count)
            for listing, count in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def listing_create_form(
    title: Annotated[str, Form(min_length=3, max_length=140)],
    category: Annotated[Category, Form()],
    condition: Annotated[Condition, Form()],
    pickup_area: Annotated[str, Form(min_length=1, max_length=160)],
    description: Annotated[str, Form(max_length=4000)] = "",
    ai_generated: Annotated[bool, Form()] = False,
) -> ListingCreate:
    """The multipart half of POST /listings, validated through ListingCreate."""
    return validate_form(
        ListingCreate,
        {
            "title": title,
            "description": description,
            "category": category,
            "condition": condition,
            "pickup_area": pickup_area,
            "ai_generated": ai_generated,
        },
    )


@router.post("", response_model=ListingRead, status_code=status.HTTP_201_CREATED)
def create_listing(
    db: DbSession,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
    payload: Annotated[ListingCreate, Depends(listing_create_form)],
    photos: Annotated[list[UploadFile], File(description="Item photos.")] = [],
    draft_photo_keys: Annotated[
        list[str], Form(description="Storage keys returned by POST /agent/draft-listing.")
    ] = [],
) -> ListingRead:
    listing = listing_service.create_listing(
        db,
        owner=current_user,
        payload=payload,
        photos=_to_uploaded(photos),
        draft_photo_keys=draft_photo_keys,
    )
    # Moderation and wishlist matching run after the response is sent, so a slow or
    # unavailable agent layer can never delay or fail a listing.
    background_tasks.add_task(agent_service.moderate_and_match, listing.id, current_user.id)
    return listing_service.to_read_model(listing, viewer=current_user)


@router.get("/{listing_id}", response_model=ListingRead)
def read_listing(listing_id: int, db: DbSession, viewer: OptionalUser) -> ListingRead:
    listing = listing_service.get_visible_listing(db, listing_id, viewer)
    count = _pending_claim_count(db, listing_id)
    return listing_service.to_read_model(listing, viewer=viewer, claim_count=count)


@router.patch("/{listing_id}", response_model=ListingRead)
def update_listing(
    listing_id: int, payload: ListingUpdate, db: DbSession, current_user: CurrentUser
) -> ListingRead:
    listing = listing_service.require_owner(
        listing_service.get_listing(db, listing_id), current_user
    )
    updated = listing_service.update_listing(db, listing=listing, payload=payload)
    count = _pending_claim_count(db, listing_id)
    return listing_service.to_read_model(updated, viewer=current_user, claim_count=count)


@router.delete("/{listing_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_listing(listing_id: int, db: DbSession, current_user: CurrentUser) -> Response:
    listing = listing_service.require_owner(
        listing_service.get_listing(db, listing_id), current_user
    )
    listing_service.delete_listing(db, listing=listing)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _pending_claim_count(db: DbSession, listing_id: int) -> int:
    """How many people are currently waiting on this listing."""
    count = db.execute(
        sa.select(sa.func.count(Claim.id)).where(
            Claim.listing_id == listing_id, Claim.status == ClaimStatus.PENDING
        )
    ).scalar_one()
    return int(count)
