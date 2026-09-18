"""Wishlist CRUD and ownership."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services.wishlist_service import MAX_WISHLIST_ITEMS
from tests.conftest import ApiUser

WISHLIST = "/api/v1/wishlist"


def add(user: ApiUser, keywords: str, category: str | None = None, expect: int = 201) -> dict:
    payload: dict[str, object] = {"keywords": keywords}
    if category is not None:
        payload["category"] = category
    response = user.client.post(WISHLIST, json=payload, headers=user.headers)
    assert response.status_code == expect, response.text
    return response.json()


def test_add_and_list_wishlist_items_newest_first(owner: ApiUser) -> None:
    add(owner, "table for studying", "furniture")
    add(owner, "calculus textbook", "books")
    response = owner.client.get(WISHLIST, headers=owner.headers)
    assert response.status_code == 200
    assert [item["keywords"] for item in response.json()] == [
        "calculus textbook",
        "table for studying",
    ]


def test_category_is_optional(owner: ApiUser) -> None:
    item = add(owner, "anything free")
    assert item["category"] is None


def test_keywords_whitespace_is_collapsed(owner: ApiUser) -> None:
    assert add(owner, "  desk    lamp  ")["keywords"] == "desk lamp"


@pytest.mark.parametrize("keywords", ["", "a", "   ", "x" * 241])
def test_invalid_keywords_are_422(owner: ApiUser, keywords: str) -> None:
    add(owner, keywords, expect=422)


def test_invalid_category_is_422(owner: ApiUser) -> None:
    add(owner, "a bicycle", "vehicles", expect=422)


def test_duplicate_entry_is_409(owner: ApiUser) -> None:
    add(owner, "study desk", "furniture")
    body = add(owner, "STUDY DESK", "furniture", expect=409)
    assert "already exists" in body["detail"]


def test_same_keywords_in_a_different_category_is_allowed(owner: ApiUser) -> None:
    add(owner, "stand", "furniture")
    add(owner, "stand", "electronics")
    assert len(owner.client.get(WISHLIST, headers=owner.headers).json()) == 2


def test_wishlist_is_capped(owner: ApiUser) -> None:
    for index in range(MAX_WISHLIST_ITEMS):
        add(owner, f"item number {index}")
    body = add(owner, "one too many", expect=409)
    assert "at most" in body["detail"]


def test_delete_removes_the_item(owner: ApiUser) -> None:
    item = add(owner, "microwave")
    response = owner.client.delete(f"{WISHLIST}/{item['id']}", headers=owner.headers)
    assert response.status_code == 204
    assert owner.client.get(WISHLIST, headers=owner.headers).json() == []


def test_cannot_delete_another_users_item(owner: ApiUser, claimer: ApiUser) -> None:
    item = add(owner, "kettle")
    # 404, not 403: the endpoint must not confirm the row exists.
    response = claimer.client.delete(f"{WISHLIST}/{item['id']}", headers=claimer.headers)
    assert response.status_code == 404
    assert len(owner.client.get(WISHLIST, headers=owner.headers).json()) == 1


def test_deleting_a_missing_item_is_404(owner: ApiUser) -> None:
    assert owner.client.delete(f"{WISHLIST}/999999", headers=owner.headers).status_code == 404


def test_wishlist_is_per_user(owner: ApiUser, claimer: ApiUser) -> None:
    add(owner, "owner wants a desk")
    add(claimer, "claimer wants a lamp")
    assert len(owner.client.get(WISHLIST, headers=owner.headers).json()) == 1
    assert owner.client.get(WISHLIST, headers=owner.headers).json()[0]["keywords"] == (
        "owner wants a desk"
    )


def test_wishlist_requires_authentication(client: TestClient) -> None:
    assert client.get(WISHLIST).status_code == 401
    assert client.post(WISHLIST, json={"keywords": "anything"}).status_code == 401
    assert client.delete(f"{WISHLIST}/1").status_code == 401
