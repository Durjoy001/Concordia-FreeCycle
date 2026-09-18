"""Authentication that is allowed to be absent (public browse endpoints)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import TokenError, decode_token
from app.database import get_db
from app.models import User

_bearer_optional = HTTPBearer(auto_error=False)


def get_optional_user(
    db: Annotated[Session, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_optional)] = None,
) -> User | None:
    """Resolve the caller if a usable token is present; never raise."""
    if credentials is None or not credentials.credentials:
        return None
    try:
        user_id = decode_token(credentials.credentials, "access")
    except TokenError:
        return None
    return db.get(User, user_id)


OptionalUser = Annotated[User | None, Depends(get_optional_user)]
