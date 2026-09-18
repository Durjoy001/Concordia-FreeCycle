"""Registration, login and token issuance."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models import User
from app.schemas.auth import TokenPair
from app.services.exceptions import AuthenticationError, Conflict, NotFound


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def issue_tokens(user: User) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        expires_in=settings.access_token_expire_minutes * 60,
    )


def get_user_by_email(db: Session, email: str) -> User | None:
    stmt = sa.select(User).where(User.email == _normalize_email(email))
    return db.execute(stmt).scalar_one_or_none()


def get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("User not found.")
    return user


def register(db: Session, *, display_name: str, email: str, password: str) -> User:
    user = User(
        email=_normalize_email(email),
        display_name=display_name.strip(),
        password_hash=hash_password(password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # Unique index on users.email - the only integrity constraint reachable here.
        raise Conflict("An account with that email already exists.") from exc
    db.refresh(user)
    return user


def authenticate(db: Session, *, email: str, password: str) -> User:
    user = get_user_by_email(db, email)
    # Same message for unknown email and wrong password so the endpoint cannot be
    # used to enumerate registered addresses.
    if user is None or not verify_password(password, user.password_hash):
        raise AuthenticationError("Incorrect email or password.")
    return user


def refresh_tokens(db: Session, refresh_token: str) -> tuple[User, TokenPair]:
    try:
        user_id = decode_token(refresh_token, "refresh")
    except TokenError as exc:
        raise AuthenticationError(str(exc)) from exc

    user = db.get(User, user_id)
    if user is None:
        raise AuthenticationError("Account no longer exists.")
    return user, issue_tokens(user)
