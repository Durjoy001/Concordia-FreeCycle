"""Engine, session factory and the FastAPI session dependency."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import Base

_connect_args: dict[str, object] = {}
if settings.database_url.startswith("sqlite"):
    # Needed because FastAPI runs sync endpoints in a worker threadpool.
    _connect_args["check_same_thread"] = False

engine: Engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
    connect_args=_connect_args,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

__all__ = ["Base", "SessionLocal", "engine", "get_db", "session_scope"]


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def session_scope() -> Session:
    """A standalone session for background tasks (caller owns commit/close)."""
    return SessionLocal()
