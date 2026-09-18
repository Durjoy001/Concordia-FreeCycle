"""Listing schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import Category, Condition, ListingStatus
from app.schemas.auth import UserPublic

T = TypeVar("T")

TitleField = Annotated[str, Field(min_length=3, max_length=140)]
DescriptionField = Annotated[str, Field(default="", max_length=4000)]
PickupAreaField = Annotated[str, Field(min_length=1, max_length=160)]


class Page(BaseModel, Generic[T]):
    """Envelope for every paginated collection."""

    items: list[T]
    total: int
    limit: int
    offset: int


class ListingBase(BaseModel):
    title: TitleField
    description: DescriptionField
    category: Category
    condition: Condition
    pickup_area: PickupAreaField

    @field_validator("title", "pickup_area", mode="after")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class ListingCreate(ListingBase):
    ai_generated: bool = False


class ListingUpdate(BaseModel):
    """Every field optional - PATCH semantics."""

    title: TitleField | None = None
    description: str | None = Field(default=None, max_length=4000)
    category: Category | None = None
    condition: Condition | None = None
    pickup_area: PickupAreaField | None = None
    status: ListingStatus | None = None

    @field_validator("title", "pickup_area", mode="after")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class ListingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner: UserPublic
    title: str
    description: str
    category: Category
    condition: Condition
    photos: list[str] = Field(description="Browser-loadable photo URLs.")
    pickup_area: str
    status: ListingStatus
    ai_generated: bool
    created_at: datetime
    updated_at: datetime
    claim_count: int = 0

    # Owner-only fields: left None for everyone else so a flagged listing never
    # explains itself to a stranger.
    flagged: bool | None = None
    flag_reason: str | None = None
    is_owner: bool = False
