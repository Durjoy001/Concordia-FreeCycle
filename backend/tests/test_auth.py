"""Auth flow: registration, login, refresh, /me."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from tests.conftest import register_user

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
ME = "/api/v1/auth/me"


def test_register_returns_user_and_token_pair(client: TestClient) -> None:
    response = client.post(
        REGISTER,
        json={
            "display_name": "Ada Lovelace",
            "email": "ada@concordia.ca",
            "password": "analytical-engine",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "ada@concordia.ca"
    assert body["user"]["display_name"] == "Ada Lovelace"
    assert "password" not in body["user"] and "password_hash" not in body["user"]
    assert body["tokens"]["token_type"] == "bearer"
    assert body["tokens"]["access_token"] != body["tokens"]["refresh_token"]
    assert body["tokens"]["expires_in"] == 30 * 60


def test_register_rejects_duplicate_email_case_insensitively(client: TestClient) -> None:
    register_user(client, email="dup@concordia.ca")
    response = client.post(
        REGISTER,
        json={"display_name": "Impostor", "email": "DUP@concordia.ca", "password": "another-pass"},
    )
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"display_name": "X", "email": "not-an-email", "password": "longenough1"}, "email"),
        ({"display_name": "X", "email": "a@b.ca", "password": "short"}, "password"),
        ({"display_name": "", "email": "a@b.ca", "password": "longenough1"}, "display_name"),
    ],
)
def test_register_validation_errors(client: TestClient, payload: dict[str, str], field: str) -> None:
    response = client.post(REGISTER, json=payload)
    assert response.status_code == 422
    assert any(field in str(err["loc"]) for err in response.json()["detail"])


def test_login_succeeds_and_is_case_insensitive_on_email(client: TestClient) -> None:
    user = register_user(client, email="login@concordia.ca", password="my-secret-pass")
    response = client.post(LOGIN, json={"email": "LOGIN@Concordia.ca", "password": "my-secret-pass"})
    assert response.status_code == 200
    assert response.json()["user"]["id"] == user.id


@pytest.mark.parametrize("password", ["wrong-password", ""])
def test_login_rejects_bad_password(client: TestClient, password: str) -> None:
    register_user(client, email="login2@concordia.ca", password="the-real-password")
    response = client.post(LOGIN, json={"email": "login2@concordia.ca", "password": password})
    assert response.status_code in (401, 422)


def test_login_unknown_email_gives_same_message_as_wrong_password(client: TestClient) -> None:
    register_user(client, email="known@concordia.ca", password="the-real-password")
    unknown = client.post(LOGIN, json={"email": "nobody@concordia.ca", "password": "whatever1"})
    wrong = client.post(LOGIN, json={"email": "known@concordia.ca", "password": "whatever1"})
    assert unknown.status_code == wrong.status_code == 401
    # No account enumeration: identical responses.
    assert unknown.json() == wrong.json()


def test_me_returns_current_user(client: TestClient) -> None:
    user = register_user(client, email="me@concordia.ca")
    response = client.get(ME, headers=user.headers)
    assert response.status_code == 200
    assert response.json()["id"] == user.id
    assert response.json()["email"] == "me@concordia.ca"


def test_me_requires_authentication(client: TestClient) -> None:
    response = client.get(ME)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_me_rejects_garbage_and_wrong_type_tokens(client: TestClient) -> None:
    user = register_user(client, email="types@concordia.ca")
    assert client.get(ME, headers={"Authorization": "Bearer not.a.token"}).status_code == 401
    # A refresh token must not work as a bearer credential.
    refresh = user.tokens["refresh_token"]
    assert client.get(ME, headers={"Authorization": f"Bearer {refresh}"}).status_code == 401


def test_me_rejects_token_for_deleted_user(client: TestClient, db) -> None:
    from app.models import User

    user = register_user(client, email="ghost@concordia.ca")
    db.delete(db.get(User, user.id))
    db.commit()
    assert client.get(ME, headers=user.headers).status_code == 401


def test_refresh_returns_a_new_usable_access_token(client: TestClient) -> None:
    user = register_user(client, email="refresh@concordia.ca")
    response = client.post(REFRESH, json={"refresh_token": user.tokens["refresh_token"]})
    assert response.status_code == 200
    tokens = response.json()
    assert tokens["token_type"] == "bearer"
    me = client.get(ME, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200
    assert me.json()["id"] == user.id


def test_refresh_rejects_an_access_token(client: TestClient) -> None:
    user = register_user(client, email="refresh2@concordia.ca")
    response = client.post(REFRESH, json={"refresh_token": user.tokens["access_token"]})
    assert response.status_code == 401


def test_refresh_rejects_garbage(client: TestClient) -> None:
    assert client.post(REFRESH, json={"refresh_token": "nope"}).status_code == 401


# --------------------------------------------------------------- unit-level: security core


def test_password_hash_is_salted_and_verifiable() -> None:
    first = hash_password("same-password")
    second = hash_password("same-password")
    assert first != second  # per-hash salt
    assert verify_password("same-password", first)
    assert verify_password("same-password", second)
    assert not verify_password("other-password", first)


def test_verify_password_tolerates_a_malformed_hash() -> None:
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_hash_password_rejects_over_72_bytes() -> None:
    with pytest.raises(ValueError, match="72 bytes"):
        hash_password("a" * 73)


def test_decode_token_round_trip_and_type_enforcement() -> None:
    assert decode_token(create_access_token(7), "access") == 7
    assert decode_token(create_refresh_token(7), "refresh") == 7
    with pytest.raises(TokenError, match="expected a refresh token"):
        decode_token(create_access_token(7), "refresh")


def test_expired_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.security as security

    monkeypatch.setattr(security.settings, "access_token_expire_minutes", -1)
    expired = create_access_token(7)
    with pytest.raises(TokenError, match="invalid or expired"):
        decode_token(expired, "access")


def test_tokens_are_unique_per_issue() -> None:
    # A jti claim keeps two tokens minted in the same second distinguishable.
    assert create_access_token(1) != create_access_token(1)
