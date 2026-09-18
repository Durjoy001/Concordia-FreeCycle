"""Listings CRUD, filtering, visibility, ownership and photo upload."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.services.exceptions import UnprocessableEntity
from app.services.storage import LocalStorageService
from tests.conftest import TINY_PNG, ApiUser, create_listing, register_user

LISTINGS = "/api/v1/listings"


# ------------------------------------------------------------------ create


def test_create_listing_returns_201_with_owner_and_defaults(owner: ApiUser) -> None:
    body = create_listing(owner)
    assert body["title"] == "Ikea study desk"
    assert body["category"] == "furniture"
    assert body["condition"] == "good"
    assert body["status"] == "available"
    assert body["ai_generated"] is False
    assert body["owner"] == {"id": owner.id, "display_name": owner.display_name}
    assert body["photos"] == []
    assert body["is_owner"] is True
    assert body["flagged"] is False  # owner sees moderation state


def test_create_listing_with_photo_stores_and_serves_it(owner: ApiUser) -> None:
    body = create_listing(owner, photo=TINY_PNG)
    assert len(body["photos"]) == 1
    url = body["photos"][0]
    assert url.startswith("/uploads/listings/")
    served = owner.client.get(url)
    assert served.status_code == 200
    assert served.content == TINY_PNG


def test_create_listing_rejects_non_image_upload(owner: ApiUser) -> None:
    response = owner.client.post(
        LISTINGS,
        data={
            "title": "Suspicious file",
            "description": "d",
            "category": "other",
            "condition": "good",
            "pickup_area": "Loyola",
        },
        files=[("photos", ("payload.pdf", b"%PDF-1.4", "application/pdf"))],
        headers=owner.headers,
    )
    assert response.status_code == 422
    assert "Unsupported image type" in response.json()["detail"]


def test_create_listing_requires_authentication(client: TestClient) -> None:
    response = client.post(
        LISTINGS,
        data={
            "title": "Anonymous couch",
            "description": "d",
            "category": "furniture",
            "condition": "good",
            "pickup_area": "Somewhere",
        },
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "override",
    [
        {"title": "ab"},                    # below min_length
        {"category": "vehicles"},           # not in the enum
        {"condition": "mint"},              # not in the enum
        {"pickup_area": "   "},             # blank after strip
    ],
)
def test_create_listing_validation(owner: ApiUser, override: dict[str, str]) -> None:
    data = {
        "title": "Valid title",
        "description": "d",
        "category": "books",
        "condition": "good",
        "pickup_area": "Hall building",
    } | override
    response = owner.client.post(LISTINGS, data=data, headers=owner.headers)
    assert response.status_code == 422


def test_create_listing_strips_whitespace(owner: ApiUser) -> None:
    body = create_listing(owner, title="  Padded title  ", pickup_area="  Sir George Williams ")
    assert body["title"] == "Padded title"
    assert body["pickup_area"] == "Sir George Williams"


def test_create_listing_rejects_unknown_draft_photo_key(owner: ApiUser) -> None:
    response = owner.client.post(
        LISTINGS,
        data={
            "title": "Adopted photo",
            "description": "d",
            "category": "other",
            "condition": "good",
            "pickup_area": "Loyola",
            "draft_photo_keys": "drafts/999/not-mine.png",
        },
        headers=owner.headers,
    )
    assert response.status_code == 422
    assert "Unknown draft photo" in response.json()["detail"]


# ------------------------------------------------------------------ browse


def test_browse_is_public_and_newest_first(client: TestClient, owner: ApiUser) -> None:
    create_listing(owner, title="First item")
    create_listing(owner, title="Second item")
    response = client.get(LISTINGS)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["title"] for item in body["items"]] == ["Second item", "First item"]


def test_browse_hides_owner_only_fields_from_strangers(client: TestClient, owner: ApiUser) -> None:
    create_listing(owner)
    item = client.get(LISTINGS).json()["items"][0]
    assert item["is_owner"] is False
    assert item["flagged"] is None
    assert item["flag_reason"] is None


def test_browse_filters_by_category(client: TestClient, owner: ApiUser) -> None:
    create_listing(owner, title="Desk", category="furniture")
    create_listing(owner, title="Calculus textbook", category="books")
    response = client.get(LISTINGS, params={"category": "books"})
    assert [i["title"] for i in response.json()["items"]] == ["Calculus textbook"]


def test_browse_search_matches_title_description_and_pickup_area(
    client: TestClient, owner: ApiUser
) -> None:
    create_listing(owner, title="Kettle", description="Boils water fast", pickup_area="Loyola")
    create_listing(owner, title="Lamp", description="Warm light", pickup_area="Guy-Concordia metro")
    assert len(client.get(LISTINGS, params={"search": "boils"}).json()["items"]) == 1
    assert len(client.get(LISTINGS, params={"search": "LOYOLA"}).json()["items"]) == 1
    assert len(client.get(LISTINGS, params={"search": "guy-concordia"}).json()["items"]) == 1
    assert len(client.get(LISTINGS, params={"search": "nonexistent"}).json()["items"]) == 0


def test_browse_pagination_reports_total_and_window(client: TestClient, owner: ApiUser) -> None:
    for index in range(5):
        create_listing(owner, title=f"Item {index}")
    response = client.get(LISTINGS, params={"limit": 2, "offset": 2})
    body = response.json()
    assert body["total"] == 5
    assert body["limit"] == 2 and body["offset"] == 2
    assert len(body["items"]) == 2


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_browse_rejects_bad_pagination(client: TestClient, params: dict[str, int]) -> None:
    assert client.get(LISTINGS, params=params).status_code == 422


def test_browse_hides_flagged_listings_but_owner_still_sees_them(
    client: TestClient, owner: ApiUser, claimer: ApiUser, db
) -> None:
    from app.services import listing_service

    listing = create_listing(owner, title="Flagged item")
    listing_service.apply_moderation(
        db, listing_id=listing["id"], flagged=True, reason="Looks like a sale attempt."
    )

    assert client.get(LISTINGS).json()["total"] == 0
    assert claimer.client.get(LISTINGS, headers=claimer.headers).json()["total"] == 0

    owner_view = owner.client.get(LISTINGS, headers=owner.headers).json()
    assert owner_view["total"] == 1
    assert owner_view["items"][0]["flagged"] is True
    assert owner_view["items"][0]["flag_reason"] == "Looks like a sale attempt."


def test_mine_filter_returns_only_callers_listings_including_removed(
    owner: ApiUser, claimer: ApiUser
) -> None:
    create_listing(owner, title="Owner item")
    create_listing(claimer, title="Claimer item")
    removed = create_listing(owner, title="Retracted item")
    owner.client.delete(f"{LISTINGS}/{removed['id']}", headers=owner.headers)

    body = owner.client.get(LISTINGS, params={"mine": True}, headers=owner.headers).json()
    titles = {item["title"] for item in body["items"]}
    assert titles == {"Owner item", "Retracted item"}


def test_mine_filter_requires_authentication(client: TestClient) -> None:
    assert client.get(LISTINGS, params={"mine": True}).status_code == 403


# ------------------------------------------------------------------ detail


def test_read_listing_by_id(client: TestClient, owner: ApiUser) -> None:
    listing = create_listing(owner)
    response = client.get(f"{LISTINGS}/{listing['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == listing["id"]


def test_read_missing_listing_is_404(client: TestClient) -> None:
    assert client.get(f"{LISTINGS}/424242").status_code == 404


def test_read_flagged_listing_is_404_for_strangers_but_visible_to_owner(
    client: TestClient, owner: ApiUser, db
) -> None:
    from app.services import listing_service

    listing = create_listing(owner)
    listing_service.apply_moderation(db, listing_id=listing["id"], flagged=True, reason="weapon")
    assert client.get(f"{LISTINGS}/{listing['id']}").status_code == 404
    owner_response = owner.client.get(f"{LISTINGS}/{listing['id']}", headers=owner.headers)
    assert owner_response.status_code == 200
    assert owner_response.json()["flag_reason"] == "weapon"


# ------------------------------------------------------------------ update / delete


def test_patch_updates_only_supplied_fields(owner: ApiUser) -> None:
    listing = create_listing(owner)
    response = owner.client.patch(
        f"{LISTINGS}/{listing['id']}",
        json={"title": "Updated desk"},
        headers=owner.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Updated desk"
    assert body["description"] == listing["description"]
    assert body["updated_at"] >= listing["updated_at"]


def test_patch_by_non_owner_is_403(owner: ApiUser, claimer: ApiUser) -> None:
    listing = create_listing(owner)
    response = claimer.client.patch(
        f"{LISTINGS}/{listing['id']}", json={"title": "Hijacked"}, headers=claimer.headers
    )
    assert response.status_code == 403


def test_patch_anonymously_is_401(client: TestClient, owner: ApiUser) -> None:
    listing = create_listing(owner)
    assert client.patch(f"{LISTINGS}/{listing['id']}", json={"title": "x"}).status_code == 401


def test_patch_cannot_fake_claimed_status(owner: ApiUser) -> None:
    listing = create_listing(owner)
    response = owner.client.patch(
        f"{LISTINGS}/{listing['id']}", json={"status": "claimed"}, headers=owner.headers
    )
    assert response.status_code == 422
    assert "accepting a claim" in response.json()["detail"]


def test_patch_cannot_complete_without_an_accepted_claim(owner: ApiUser) -> None:
    listing = create_listing(owner)
    response = owner.client.patch(
        f"{LISTINGS}/{listing['id']}", json={"status": "completed"}, headers=owner.headers
    )
    assert response.status_code == 422


def test_delete_soft_removes_and_hides_the_listing(client: TestClient, owner: ApiUser) -> None:
    listing = create_listing(owner)
    response = owner.client.delete(f"{LISTINGS}/{listing['id']}", headers=owner.headers)
    assert response.status_code == 204
    assert client.get(f"{LISTINGS}/{listing['id']}").status_code == 404
    # The owner keeps their history.
    owner_view = owner.client.get(f"{LISTINGS}/{listing['id']}", headers=owner.headers)
    assert owner_view.status_code == 200
    assert owner_view.json()["status"] == "removed"


def test_delete_by_non_owner_is_403(owner: ApiUser, claimer: ApiUser) -> None:
    listing = create_listing(owner)
    assert claimer.client.delete(
        f"{LISTINGS}/{listing['id']}", headers=claimer.headers
    ).status_code == 403


def test_patch_missing_listing_is_404(owner: ApiUser) -> None:
    assert owner.client.patch(
        f"{LISTINGS}/999999", json={"title": "ghost"}, headers=owner.headers
    ).status_code == 404


# ------------------------------------------------------------------ storage unit tests


def test_storage_round_trip(upload_root) -> None:
    store = LocalStorageService(root=upload_root, base_url="/uploads")
    key = store.save(io.BytesIO(TINY_PNG), prefix="listings/1", content_type="image/png")
    assert key.startswith("listings/1/") and key.endswith(".png")
    assert store.exists(key)
    assert store.local_path(key).read_bytes() == TINY_PNG
    assert store.public_url(key) == f"/uploads/{key}"
    store.delete(key)
    assert not store.exists(key)
    store.delete(key)  # deleting twice is not an error


def test_storage_rejects_oversized_upload_and_leaves_no_file(upload_root) -> None:
    store = LocalStorageService(root=upload_root, base_url="/uploads", max_bytes=16)
    with pytest.raises(UnprocessableEntity, match="exceeds"):
        store.save(io.BytesIO(b"x" * 64), prefix="listings/1", content_type="image/png")
    assert list((upload_root / "listings" / "1").glob("*")) == []


def test_storage_rejects_empty_upload(upload_root) -> None:
    store = LocalStorageService(root=upload_root, base_url="/uploads")
    with pytest.raises(UnprocessableEntity, match="empty"):
        store.save(io.BytesIO(b""), prefix="listings/1", content_type="image/png")


@pytest.mark.parametrize("key", ["../escape.png", "/etc/passwd", "", "a/../../b.png"])
def test_storage_refuses_path_traversal(upload_root, key: str) -> None:
    store = LocalStorageService(root=upload_root, base_url="/uploads")
    with pytest.raises(UnprocessableEntity, match="Invalid storage key"):
        store.local_path(key)


def test_storage_rejects_unsupported_content_type(upload_root) -> None:
    store = LocalStorageService(root=upload_root, base_url="/uploads")
    with pytest.raises(UnprocessableEntity, match="Unsupported image type"):
        store.save(io.BytesIO(b"data"), prefix="listings/1", content_type="text/plain")


def test_storage_accepts_content_type_with_parameters(upload_root) -> None:
    store = LocalStorageService(root=upload_root, base_url="/uploads")
    key = store.save(io.BytesIO(TINY_PNG), prefix="p", content_type="image/png; charset=binary")
    assert key.endswith(".png")
