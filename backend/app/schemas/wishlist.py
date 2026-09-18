"""Wishlist schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import Category


class WishlistItemCreate(BaseModel):
    keywords: Annotated[str, Field(min_length=2, max_length=240)]
    category: Category | None = None

    @field_validator("keywords", mode="after")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = " ".join(value.split())
        if len(stripped) < 2:
            raise ValueError("must contain at least 2 characters")
        return stripped


class WishlistItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    keywords: str
    category: Category | None
    created_at: datetime
