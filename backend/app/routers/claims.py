"""Claim endpoints: nested under a listing for creation/listing, flat for mutation."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.core.deps import CurrentUser, DbSession
from app.models import ClaimStatus
from app.schemas.claim import ClaimAction, ClaimCreate, ClaimRead, ClaimWithPickup
from app.services import agent_service, claim_service, listing_service

listing_claims_router = APIRouter(prefix="/listings", tags=["claims"])
claims_router = APIRouter(prefix="/claims", tags=["claims"])


@listing_claims_router.post(
    "/{listing_id}/claims", response_model=ClaimRead, status_code=status.HTTP_201_CREATED
)
def create_claim(
    listing_id: int, payload: ClaimCreate, db: DbSession, current_user: CurrentUser
) -> ClaimRead:
    claim = claim_service.create_claim(
        db, listing_id=listing_id, claimer=current_user, message=payload.message
    )
    return ClaimRead.model_validate(claim)


@listing_claims_router.get("/{listing_id}/claims", response_model=list[ClaimRead])
def list_listing_claims(
    listing_id: int, db: DbSession, current_user: CurrentUser
) -> list[ClaimRead]:
    """Owner only - the queue of people who want the item."""
    listing = listing_service.get_listing(db, listing_id)
    claims = claim_service.list_claims_for_listing(db, listing=listing, requester=current_user)
    return [ClaimRead.model_validate(claim) for claim in claims]


@claims_router.get("/mine", response_model=list[ClaimWithPickup])
def list_my_claims(db: DbSession, current_user: CurrentUser) -> list[ClaimWithPickup]:
    """The caller's own claims, with pickup details once one is accepted."""
    results: list[ClaimWithPickup] = []
    for claim in claim_service.list_claims_by_user(db, user=current_user):
        pickup = None
        if claim.status in (ClaimStatus.ACCEPTED, ClaimStatus.COMPLETED):
            pickup = claim_service.build_pickup_details(db, claim=claim)
        results.append(ClaimWithPickup(claim=ClaimRead.model_validate(claim), pickup=pickup))
    return results


@claims_router.patch("/{claim_id}", response_model=ClaimWithPickup)
def update_claim(
    claim_id: int, payload: ClaimAction, db: DbSession, current_user: CurrentUser
) -> ClaimWithPickup:
    """accept/decline (owner), cancel (claimer), complete (either party)."""
    claim = claim_service.get_claim(db, claim_id)

    if payload.action == "accept":
        claim = claim_service.accept_claim(db, claim=claim, actor=current_user)
    elif payload.action == "decline":
        claim = claim_service.decline_claim(db, claim=claim, actor=current_user)
    elif payload.action == "cancel":
        claim = claim_service.cancel_claim(db, claim=claim, actor=current_user)
    else:
        claim = claim_service.complete_claim(db, claim=claim, actor=current_user)

    pickup = None
    if claim.status in (ClaimStatus.ACCEPTED, ClaimStatus.COMPLETED):
        drafted = None
        if payload.action == "accept":
            # Synchronous on purpose: the owner needs the message in this response.
            # A None result simply means the copy button has nothing to offer.
            drafted = agent_service.draft_pickup_message(
                db,
                listing_id=claim.listing_id,
                claim_id=claim.id,
                user_id=current_user.id,
            )
            claim_service.store_drafted_message(db, claim=claim, message=drafted)
        pickup = claim_service.build_pickup_details(db, claim=claim, drafted_message=drafted)
    return ClaimWithPickup(claim=ClaimRead.model_validate(claim), pickup=pickup)
