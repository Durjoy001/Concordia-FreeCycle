"""Claim schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import ClaimStatus
from app.schemas.auth import UserPublic

MessageField = Annotated[str, Field(max_length=1000)]


class ClaimCreate(BaseModel):
    message: MessageField = ""


class ClaimAction(BaseModel):
    """PATCH /claims/{id} - the owner accepts/declines, the claimer cancels."""

    action: Literal["accept", "decline", "cancel", "complete"]


class ClaimRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    listing_id: int
    claimer: UserPublic
    message: str
    status: ClaimStatus
    created_at: datetime
    drafted_message: str | None = Field(
        default=None, description="AI-drafted pickup message; set once the claim is accepted."
    )


class PickupDetails(BaseModel):
    """Contact + AI-drafted coordination message, released only on acceptance."""

    owner_display_name: str
    owner_email: EmailStr
    claimer_display_name: str
    pickup_area: str
    drafted_message: str | None = Field(
        default=None,
        description="AI-drafted pickup message; null if the agent layer was unavailable.",
    )


class ClaimWithPickup(BaseModel):
    claim: ClaimRead
    pickup: PickupDetails | None = None
