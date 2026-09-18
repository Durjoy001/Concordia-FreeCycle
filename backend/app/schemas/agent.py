"""Agent endpoint schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.enums import Category, Condition


class DraftedListing(BaseModel):
    """AI-drafted listing fields, for the student to review and edit."""

    title: str = Field(max_length=140)
    description: str = Field(max_length=1200)
    category: Category
    condition: Condition
    confidence: float = Field(ge=0, le=1, description="0..1 identification confidence.")
    photo_key: str = Field(
        description="Pass this back as draft_photo_keys on POST /listings to reuse the upload."
    )
    flagged: bool = Field(
        default=False, description="True when the drafted item breaks the prohibited-items rules."
    )
    flag_reason: str | None = None
    summary: str = ""
    tools_used: list[str] = Field(
        default_factory=list, description="MCP tools the agent chose to call, in order."
    )
