"""Domain enumerations, shared by models and Pydantic schemas."""

from __future__ import annotations

from enum import Enum


class Category(str, Enum):
    FURNITURE = "furniture"
    BOOKS = "books"
    ELECTRONICS = "electronics"
    KITCHEN = "kitchen"
    CLOTHING = "clothing"
    OTHER = "other"


class Condition(str, Enum):
    LIKE_NEW = "like_new"
    GOOD = "good"
    FAIR = "fair"
    WORN = "worn"


class ListingStatus(str, Enum):
    AVAILABLE = "available"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    REMOVED = "removed"


class ClaimStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    COMPLETED = "completed"


class NotificationType(str, Enum):
    WISHLIST_MATCH = "wishlist_match"
    CLAIM_RECEIVED = "claim_received"
    CLAIM_ACCEPTED = "claim_accepted"


class AgentTask(str, Enum):
    """Orchestrator entry points, used for budget accounting and observability."""

    DRAFT_LISTING = "draft_listing"
    MODERATE_LISTING = "moderate_listing"
    RUN_MATCHING = "run_matching"
    DRAFT_PICKUP_MESSAGE = "draft_pickup_message"


class AgentRunStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BUDGET_EXCEEDED = "budget_exceeded"
