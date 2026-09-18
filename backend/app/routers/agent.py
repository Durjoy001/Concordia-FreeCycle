"""/agent endpoints - the interactive half of the agent layer."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from app.core.deps import CurrentUser, DbSession
from app.schemas.agent import DraftedListing
from app.services import agent_service
from app.services.exceptions import UnprocessableEntity

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/draft-listing", response_model=DraftedListing)
def draft_listing(
    db: DbSession,
    current_user: CurrentUser,
    photo: Annotated[UploadFile, File(description="Photo of the item to draft a listing for.")],
) -> DraftedListing:
    """Run the drafting agent over an uploaded photo.

    The photo is stored once, under the caller's draft prefix, and its key comes
    back in the response: POST /listings adopts it instead of re-uploading. Nothing
    is created here - the student edits and confirms first.
    """
    if not photo.filename:
        raise UnprocessableEntity("A photo file is required.")

    photo_key = agent_service.stage_draft_photo(
        user_id=current_user.id, stream=photo.file, content_type=photo.content_type
    )
    drafted = agent_service.draft_listing_from_photo(
        db, user_id=current_user.id, photo_key=photo_key
    )
    return DraftedListing.model_validate(drafted)
