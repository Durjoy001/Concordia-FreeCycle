"""Password hashing and JWT access/refresh token handling."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Final, Literal

import bcrypt
import jwt
from jwt import InvalidTokenError

from app.config import settings

TokenType = Literal["access", "refresh"]

# bcrypt truncates silently past 72 bytes, so the API rejects longer passwords upstream
# (see app.schemas.auth) rather than hashing a silently-cut secret.
MAX_PASSWORD_BYTES: Final[int] = 72
_BCRYPT_ROUNDS: Final[int] = 12


class TokenError(Exception):
    """Raised when a token is missing, malformed, expired or of the wrong type."""


def hash_password(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError(f"password must be at most {MAX_PASSWORD_BYTES} bytes")
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(encoded, password_hash.encode("utf-8"))
    except ValueError:
        # Malformed/legacy hash in the row - treat as a failed login, never a 500.
        return False


def _create_token(subject: int, token_type: TokenType, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: int) -> str:
    return _create_token(
        user_id, "access", timedelta(minutes=settings.access_token_expire_minutes)
    )


def create_refresh_token(user_id: int) -> str:
    return _create_token(user_id, "refresh", timedelta(days=settings.refresh_token_expire_days))


def decode_token(token: str, expected_type: TokenType) -> int:
    """Return the user id encoded in `token`, or raise TokenError."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except InvalidTokenError as exc:
        raise TokenError("invalid or expired token") from exc

    if payload.get("type") != expected_type:
        # Refusing an access token at /auth/refresh (and vice versa) is deliberate:
        # a long-lived refresh token must not be usable as a bearer credential.
        raise TokenError(f"expected a {expected_type} token")

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject.isdigit():
        raise TokenError("token subject is missing or malformed")
    return int(subject)
