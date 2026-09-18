"""Claims flow, end to end."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import ApiUser, create_listing, register_user

LISTINGS = "/api/v1/listings"
CLAIMS = "/api/v1/claims"


def claim(user: ApiUser, listing_id: int, message: str = "Hi! Can I pick it up Friday?",
          expect: int = 201) -> dict:
    response = user.client.post(
        f"{LISTINGS}/{listing_id}/claims", json={"message": message}, headers=user.headers
    )
    assert response.status_code == expect, response.text
    return response.json()


def act(user: ApiUser, claim_id: int, action: str, expect: int = 200) -> dict:
    response = user.client.patch(
        f"{CLAIMS}/{claim_id}", json={"action": action}, headers=user.headers
    )
    assert response.status_code == expect, response.text
    return response.json()


# ------------------------------------------------------------------ happy path


def test_full_claim_lifecycle(owner: ApiUser, claimer: ApiUser) -> None:
    """Create -> claim -> owner accepts -> pickup details -> complete."""
    listing = create_listing(owner)

    created = claim(claimer, listing["id"])
    assert created["status"] == "pending"
    assert created["claimer"] == {"id": claimer.id, "display_name": claimer.display_name}
    assert created["message"] == "Hi! Can I pick it up Friday?"

    # Owner sees the claim in their queue.
    queue = owner.client.get(f"{LISTINGS}/{listing['id']}/claims", headers=owner.headers).json()
    assert [c["id"] for c in queue] == [created["id"]]

    # A pending claim shows up in the listing's claim_count.
    detail = owner.client.get(f"{LISTINGS}/{listing['id']}", headers=owner.headers).json()
    assert detail["claim_count"] == 1

    accepted = act(owner, created["id"], "accept")
    assert accepted["claim"]["status"] == "accepted"
    pickup = accepted["pickup"]
    assert pickup["owner_email"] == owner.email
    assert pickup["owner_display_name"] == owner.display_name
    assert pickup["claimer_display_name"] == claimer.display_name
    assert pickup["pickup_area"] == "Guy-Concordia metro"

    # The listing is now claimed.
    listing_after = owner.client.get(f"{LISTINGS}/{listing['id']}", headers=owner.headers).json()
    assert listing_after["status"] == "claimed"

    completed = act(claimer, created["id"], "complete")
    assert completed["claim"]["status"] == "completed"
    final = owner.client.get(f"{LISTINGS}/{listing['id']}", headers=owner.headers).json()
    assert final["status"] == "completed"


def test_accepting_one_claim_declines_the_others(
    owner: ApiUser, claimer: ApiUser, client: TestClient
) -> None:
    third = register_user(client, email="third@concordia.ca", display_name="Third Tamara")
    listing = create_listing(owner)
    first = claim(claimer, listing["id"])
    second = claim(third, listing["id"])

    act(owner, first["id"], "accept")

    queue = owner.client.get(f"{LISTINGS}/{listing['id']}/claims", headers=owner.headers).json()
    by_id = {c["id"]: c["status"] for c in queue}
    assert by_id[first["id"]] == "accepted"
    assert by_id[second["id"]] == "declined"


# ------------------------------------------------------------------ the one-accepted invariant


def test_only_one_claim_can_be_accepted(owner: ApiUser, claimer: ApiUser, client: TestClient) -> None:
    third = register_user(client, email="third2@concordia.ca")
    listing = create_listing(owner)
    first = claim(claimer, listing["id"])
    second = claim(third, listing["id"])
    act(owner, first["id"], "accept")

    # The second is already declined by the accept above, so accepting is a conflict.
    body = act(owner, second["id"], "accept", expect=409)
    assert "declined" in body["detail"] or "already been accepted" in body["detail"]


def test_accept_is_idempotent(owner: ApiUser, claimer: ApiUser) -> None:
    listing = create_listing(owner)
    created = claim(claimer, listing["id"])
    act(owner, created["id"], "accept")
    again = act(owner, created["id"], "accept")
    assert again["claim"]["status"] == "accepted"


def test_claiming_twice_is_a_conflict(owner: ApiUser, claimer: ApiUser) -> None:
    listing = create_listing(owner)
    claim(claimer, listing["id"])
    body = claim(claimer, listing["id"], expect=409)
    assert "already claimed" in body["detail"]


def test_cannot_claim_a_listing_that_is_already_claimed(
    owner: ApiUser, claimer: ApiUser, client: TestClient
) -> None:
    latecomer = register_user(client, email="late@concordia.ca")
    listing = create_listing(owner)
    first = claim(claimer, listing["id"])
    act(owner, first["id"], "accept")
    body = claim(latecomer, listing["id"], expect=409)
    assert "no longer available" in body["detail"]


# ------------------------------------------------------------------ authorisation


def test_owner_cannot_claim_their_own_listing(owner: ApiUser) -> None:
    listing = create_listing(owner)
    body = claim(owner, listing["id"], expect=422)
    assert "your own listing" in body["detail"]


def test_claim_requires_authentication(client: TestClient, owner: ApiUser) -> None:
    listing = create_listing(owner)
    assert client.post(f"{LISTINGS}/{listing['id']}/claims", json={"message": "hi"}).status_code == 401


def test_only_the_owner_can_see_the_claim_queue(owner: ApiUser, claimer: ApiUser) -> None:
    listing = create_listing(owner)
    claim(claimer, listing["id"])
    response = claimer.client.get(f"{LISTINGS}/{listing['id']}/claims", headers=claimer.headers)
    assert response.status_code == 403


def test_non_owner_cannot_accept_or_decline(owner: ApiUser, claimer: ApiUser) -> None:
    listing = create_listing(owner)
    created = claim(claimer, listing["id"])
    assert act(claimer, created["id"], "accept", expect=403)
    assert act(claimer, created["id"], "decline", expect=403)


def test_owner_cannot_cancel_someone_elses_claim(owner: ApiUser, claimer: ApiUser) -> None:
    listing = create_listing(owner)
    created = claim(claimer, listing["id"])
    body = act(owner, created["id"], "cancel", expect=403)
    assert "Only the claimer" in body["detail"]


def test_unrelated_user_cannot_touch_a_claim(
    owner: ApiUser, claimer: ApiUser, client: TestClient
) -> None:
    stranger = register_user(client, email="stranger@concordia.ca")
    listing = create_listing(owner)
    created = claim(claimer, listing["id"])
    act(stranger, created["id"], "accept", expect=403)
    act(stranger, created["id"], "cancel", expect=403)
    act(stranger, created["id"], "complete", expect=403)


def test_pickup_email_is_not_exposed_before_acceptance(owner: ApiUser, claimer: ApiUser) -> None:
    listing = create_listing(owner)
    created = claim(claimer, listing["id"])
    mine = claimer.client.get(f"{CLAIMS}/mine", headers=claimer.headers).json()
    assert mine[0]["claim"]["id"] == created["id"]
    assert mine[0]["pickup"] is None  # no owner email while still pending


def test_claimer_sees_pickup_details_after_acceptance(owner: ApiUser, claimer: ApiUser) -> None:
    listing = create_listing(owner)
    created = claim(claimer, listing["id"])
    act(owner, created["id"], "accept")
    mine = claimer.client.get(f"{CLAIMS}/mine", headers=claimer.headers).json()
    assert mine[0]["pickup"]["owner_email"] == owner.email


# ------------------------------------------------------------------ decline / cancel


def test_decline_leaves_the_listing_available(owner: ApiUser, claimer: ApiUser) -> None:
    listing = create_listing(owner)
    created = claim(claimer, listing["id"])
    declined = act(owner, created["id"], "decline")
    assert declined["claim"]["status"] == "declined"
    assert declined["pickup"] is None
    detail = owner.client.get(f"{LISTINGS}/{listing['id']}", headers=owner.headers).json()
    assert detail["status"] == "available"


def test_cancelling_an_accepted_claim_releases_the_listing(
    owner: ApiUser, claimer: ApiUser
) -> None:
    listing = create_listing(owner)
    created = claim(claimer, listing["id"])
    act(owner, created["id"], "accept")
    act(claimer, created["id"], "cancel")
    detail = owner.client.get(f"{LISTINGS}/{listing['id']}", headers=owner.headers).json()
    assert detail["status"] == "available"


def test_a_released_listing_can_be_claimed_again(
    owner: ApiUser, claimer: ApiUser, client: TestClient
) -> None:
    second_claimer = register_user(client, email="second@concordia.ca")
    listing = create_listing(owner)
    first = claim(claimer, listing["id"])
    act(owner, first["id"], "accept")
    act(claimer, first["id"], "cancel")
    retry = claim(second_claimer, listing["id"])
    assert retry["status"] == "pending"


def test_cannot_decline_an_accepted_claim(owner: ApiUser, claimer: ApiUser) -> None:
    listing = create_listing(owner)
    created = claim(claimer, listing["id"])
    act(owner, created["id"], "accept")
    body = act(owner, created["id"], "decline", expect=409)
    assert "already accepted" in body["detail"]


def test_cannot_complete_a_pending_claim(owner: ApiUser, claimer: ApiUser) -> None:
    listing = create_listing(owner)
    created = claim(claimer, listing["id"])
    body = act(owner, created["id"], "complete", expect=409)
    assert "accepted claim" in body["detail"]


def test_cannot_cancel_a_completed_claim(owner: ApiUser, claimer: ApiUser) -> None:
    listing = create_listing(owner)
    created = claim(claimer, listing["id"])
    act(owner, created["id"], "accept")
    act(owner, created["id"], "complete")
    act(claimer, created["id"], "cancel", expect=409)


# ------------------------------------------------------------------ edges


def test_claiming_a_missing_listing_is_404(claimer: ApiUser) -> None:
    claim(claimer, 999999, expect=404)


def test_claiming_a_flagged_listing_is_404(owner: ApiUser, claimer: ApiUser, db) -> None:
    from app.services import listing_service

    listing = create_listing(owner)
    listing_service.apply_moderation(db, listing_id=listing["id"], flagged=True, reason="alcohol")
    claim(claimer, listing["id"], expect=404)


def test_claiming_a_removed_listing_is_404(owner: ApiUser, claimer: ApiUser) -> None:
    listing = create_listing(owner)
    owner.client.delete(f"{LISTINGS}/{listing['id']}", headers=owner.headers)
    claim(claimer, listing["id"], expect=404)


def test_patching_a_missing_claim_is_404(owner: ApiUser) -> None:
    act(owner, 999999, "accept", expect=404)


@pytest.mark.parametrize("action", ["approve", "", "ACCEPT", "delete"])
def test_unknown_action_is_422(owner: ApiUser, claimer: ApiUser, action: str) -> None:
    listing = create_listing(owner)
    created = claim(claimer, listing["id"])
    act(owner, created["id"], action, expect=422)


def test_claim_message_length_is_capped(owner: ApiUser, claimer: ApiUser) -> None:
    listing = create_listing(owner)
    claim(claimer, listing["id"], message="x" * 1001, expect=422)


def test_claim_message_may_be_empty(owner: ApiUser, claimer: ApiUser) -> None:
    listing = create_listing(owner)
    created = claim(claimer, listing["id"], message="")
    assert created["message"] == ""
