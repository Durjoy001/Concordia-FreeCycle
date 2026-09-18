"""Claim lifecycle.

Invariants enforced here:
  * a listing may have at most one ACCEPTED claim;
  * accepting one flips the listing to CLAIMED and declines every other pending claim;
  * an owner cannot claim their own listing;
  * only the owner accepts/declines; only the claimer cancels.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import Claim, ClaimStatus, Listing, ListingStatus, User, utcnow
from app.services import notification_service
from app.services.exceptions import (
    Conflict,
    NotFound,
    PermissionDenied,
    UnprocessableEntity,
)
from app.services.listing_service import get_listing

_OPEN_STATUSES = (ClaimStatus.PENDING, ClaimStatus.ACCEPTED)


def get_claim(db: Session, claim_id: int) -> Claim:
    stmt = (
        sa.select(Claim)
        .options(selectinload(Claim.claimer), selectinload(Claim.listing))
        .where(Claim.id == claim_id)
    )
    claim = db.execute(stmt).scalar_one_or_none()
    if claim is None:
        raise NotFound("Claim not found.")
    return claim


def accepted_claim_for(db: Session, listing_id: int) -> Claim | None:
    stmt = (
        sa.select(Claim)
        .options(selectinload(Claim.claimer))
        .where(Claim.listing_id == listing_id, Claim.status == ClaimStatus.ACCEPTED)
    )
    return db.execute(stmt).scalars().first()


def list_claims_for_listing(db: Session, *, listing: Listing, requester: User) -> list[Claim]:
    if listing.owner_id != requester.id:
        raise PermissionDenied("Only the listing owner can see its claims.")
    stmt = (
        sa.select(Claim)
        .options(selectinload(Claim.claimer))
        .where(Claim.listing_id == listing.id)
        .order_by(Claim.created_at.asc(), Claim.id.asc())
    )
    return list(db.execute(stmt).scalars().all())


def list_claims_by_user(db: Session, *, user: User) -> list[Claim]:
    stmt = (
        sa.select(Claim)
        .options(selectinload(Claim.claimer), selectinload(Claim.listing))
        .where(Claim.claimer_id == user.id)
        .order_by(Claim.created_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


def create_claim(db: Session, *, listing_id: int, claimer: User, message: str) -> Claim:
    listing = get_listing(db, listing_id)

    if listing.flagged or listing.status == ListingStatus.REMOVED:
        # Consistent with GET: a hidden listing must not confirm it exists.
        raise NotFound("Listing not found.")
    if listing.owner_id == claimer.id:
        raise UnprocessableEntity("You cannot claim your own listing.")
    if listing.status != ListingStatus.AVAILABLE:
        raise Conflict(f"This listing is no longer available (status: {listing.status.value}).")

    claim = Claim(
        listing_id=listing.id,
        claimer_id=claimer.id,
        message=message.strip(),
        status=ClaimStatus.PENDING,
    )
    db.add(claim)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # uq_claim_listing_claimer - the same student claiming twice.
        raise Conflict("You have already claimed this listing.") from exc
    db.refresh(claim)

    notification_service.notify_claim_received(
        db, listing=listing, claim=claim, claimer=claimer
    )
    return claim


def accept_claim(db: Session, *, claim: Claim, actor: User) -> Claim:
    listing = claim.listing
    if listing.owner_id != actor.id:
        raise PermissionDenied("Only the listing owner can accept a claim.")
    if claim.status == ClaimStatus.ACCEPTED:
        return claim
    if claim.status != ClaimStatus.PENDING:
        raise Conflict(f"Cannot accept a claim that is already {claim.status.value}.")

    existing = accepted_claim_for(db, listing.id)
    if existing is not None and existing.id != claim.id:
        raise Conflict("Another claim on this listing has already been accepted.")

    claim.status = ClaimStatus.ACCEPTED
    # Everyone else on this listing is told no, in the same transaction.
    db.execute(
        sa.update(Claim)
        .where(
            Claim.listing_id == listing.id,
            Claim.id != claim.id,
            Claim.status == ClaimStatus.PENDING,
        )
        .values(status=ClaimStatus.DECLINED)
    )
    listing.status = ListingStatus.CLAIMED
    listing.updated_at = utcnow()
    db.commit()
    db.refresh(claim)

    owner = db.get(User, listing.owner_id)
    if owner is not None:
        notification_service.notify_claim_accepted(
            db, listing=listing, claim=claim, owner=owner
        )
    return claim


def decline_claim(db: Session, *, claim: Claim, actor: User) -> Claim:
    listing = claim.listing
    if listing.owner_id != actor.id:
        raise PermissionDenied("Only the listing owner can decline a claim.")
    if claim.status == ClaimStatus.DECLINED:
        return claim
    if claim.status != ClaimStatus.PENDING:
        raise Conflict(f"Cannot decline a claim that is already {claim.status.value}.")

    claim.status = ClaimStatus.DECLINED
    db.commit()
    db.refresh(claim)
    return claim


def cancel_claim(db: Session, *, claim: Claim, actor: User) -> Claim:
    """The claimer withdraws. An accepted claim releases the listing again."""
    if claim.claimer_id != actor.id:
        raise PermissionDenied("Only the claimer can cancel their own claim.")
    if claim.status not in _OPEN_STATUSES:
        raise Conflict(f"Cannot cancel a claim that is already {claim.status.value}.")

    was_accepted = claim.status == ClaimStatus.ACCEPTED
    claim.status = ClaimStatus.DECLINED
    if was_accepted and claim.listing.status == ListingStatus.CLAIMED:
        claim.listing.status = ListingStatus.AVAILABLE
        claim.listing.updated_at = utcnow()
    db.commit()
    db.refresh(claim)
    return claim


def complete_claim(db: Session, *, claim: Claim, actor: User) -> Claim:
    """Either party confirms the handover happened."""
    listing = claim.listing
    if actor.id not in (listing.owner_id, claim.claimer_id):
        raise PermissionDenied("Only the owner or the claimer can complete this claim.")
    if claim.status == ClaimStatus.COMPLETED:
        return claim
    if claim.status != ClaimStatus.ACCEPTED:
        raise Conflict("Only an accepted claim can be completed.")

    claim.status = ClaimStatus.COMPLETED
    listing.status = ListingStatus.COMPLETED
    listing.updated_at = utcnow()
    db.commit()
    db.refresh(claim)
    return claim


def build_pickup_details(
    db: Session, *, claim: Claim, drafted_message: str | None = None
) -> "PickupDetails":
    """Contact details for an accepted claim.

    The owner's email is released here and nowhere else - the two parties need a
    channel once a handover is agreed, but a pending claim must not leak it.
    """
    from app.schemas.claim import PickupDetails

    listing = claim.listing
    owner = db.get(User, listing.owner_id)
    if owner is None:  # pragma: no cover - FK guarantees the row
        raise NotFound("Listing owner no longer exists.")
    return PickupDetails(
        owner_display_name=owner.display_name,
        owner_email=owner.email,
        claimer_display_name=claim.claimer.display_name,
        pickup_area=listing.pickup_area,
        drafted_message=drafted_message or claim.drafted_message,
    )


def store_drafted_message(db: Session, *, claim: Claim, message: str | None) -> Claim:
    """Persist the agent's pickup draft so it survives a reload."""
    if message:
        claim.drafted_message = message
        db.commit()
        db.refresh(claim)
    return claim
