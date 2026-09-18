"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import TokenError, decode_token
from app.database import get_db
from app.models import User
from app.services.exceptions import AuthenticationError

# auto_error=False so a missing header raises our own 401 with a WWW-Authenticate
# header rather than FastAPI's bare 403.
_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> User:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Not authenticated.")
    try:
        user_id = decode_token(credentials.credentials, "access")
    except TokenError as exc:
        raise AuthenticationError(str(exc)) from exc

    user = db.get(User, user_id)
    if user is None:
        raise AuthenticationError("Account no longer exists.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
