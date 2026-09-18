"""/auth endpoints."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.core.deps import CurrentUser, DbSession
from app.models import User
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserMe,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: DbSession) -> AuthResponse:
    user: User = auth_service.register(
        db,
        display_name=payload.display_name,
        email=payload.email,
        password=payload.password,
    )
    return AuthResponse(user=UserMe.model_validate(user), tokens=auth_service.issue_tokens(user))


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: DbSession) -> AuthResponse:
    user = auth_service.authenticate(db, email=payload.email, password=payload.password)
    return AuthResponse(user=UserMe.model_validate(user), tokens=auth_service.issue_tokens(user))


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, db: DbSession) -> TokenPair:
    _, tokens = auth_service.refresh_tokens(db, payload.refresh_token)
    return tokens


@router.get("/me", response_model=UserMe)
def me(current_user: CurrentUser) -> UserMe:
    return UserMe.model_validate(current_user)
