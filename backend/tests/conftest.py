"""Shared pytest fixtures.

Environment is set before any `app.*` import so pydantic-settings picks up the
test database and upload directory (env vars win over any local .env file).
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

_TMP_ROOT = Path(tempfile.mkdtemp(prefix="freecycle-tests-"))

os.environ.update(
    DATABASE_URL=f"sqlite:///{_TMP_ROOT / 'test.sqlite3'}",
    UPLOAD_DIR=str(_TMP_ROOT / "uploads"),
    JWT_SECRET="test-secret-not-for-production-0123456789",
    ACCESS_TOKEN_EXPIRE_MINUTES="30",
    REFRESH_TOKEN_EXPIRE_DAYS="14",
    ANTHROPIC_API_KEY="test-key",
    ANTHROPIC_MODEL="claude-sonnet-4-6",
    AGENT_DAILY_BUDGET="20",
    # Off by default so no test accidentally reaches the network or spawns the MCP
    # server; tests/test_agent.py turns it on explicitly with fakes in place.
    AGENT_ENABLED="false",
    MCP_TRANSPORT="stdio",
    CORS_ORIGINS="http://testserver",
)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_schema() -> Generator[None, None, None]:
    """Every test starts from an empty database."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def upload_root(tmp_path: Path) -> Path:
    """An isolated storage root per test, so blob assertions cannot see each other."""
    path = tmp_path / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


# --------------------------------------------------------------------------- helpers


class ApiUser:
    """A registered user plus the headers needed to act as them."""

    def __init__(self, client: TestClient, user_id: int, email: str, display_name: str,
                 password: str, tokens: dict[str, str]) -> None:
        self.client = client
        self.id = user_id
        self.email = email
        self.display_name = display_name
        self.password = password
        self.tokens = tokens

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens['access_token']}"}


def register_user(
    client: TestClient,
    email: str = "student@concordia.ca",
    display_name: str = "Test Student",
    password: str = "correct-horse-battery",
) -> ApiUser:
    response = client.post(
        "/api/v1/auth/register",
        json={"display_name": display_name, "email": email, "password": password},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return ApiUser(
        client=client,
        user_id=body["user"]["id"],
        email=body["user"]["email"],
        display_name=body["user"]["display_name"],
        password=password,
        tokens=body["tokens"],
    )


@pytest.fixture
def owner(client: TestClient) -> ApiUser:
    return register_user(client, email="owner@concordia.ca", display_name="Owner Olivia")


@pytest.fixture
def claimer(client: TestClient) -> ApiUser:
    return register_user(client, email="claimer@concordia.ca", display_name="Claimer Chris")


# 1x1 PNG - smallest valid raster payload for upload tests.
TINY_PNG: bytes = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def create_listing(
    user: ApiUser,
    *,
    title: str = "Ikea study desk",
    description: str = "Sturdy white desk, small ink mark on one corner.",
    category: str = "furniture",
    condition: str = "good",
    pickup_area: str = "Guy-Concordia metro",
    ai_generated: bool = False,
    photo: bytes | None = None,
    expect: int = 201,
) -> dict:
    """Create a listing through the multipart endpoint."""
    data = {
        "title": title,
        "description": description,
        "category": category,
        "condition": condition,
        "pickup_area": pickup_area,
        "ai_generated": str(ai_generated).lower(),
    }
    files = [("photos", ("item.png", photo, "image/png"))] if photo is not None else None
    response = user.client.post(
        "/api/v1/listings", data=data, files=files, headers=user.headers
    )
    assert response.status_code == expect, response.text
    return response.json()


# ------------------------------------------------- the MCP server, in-process

# The agent tests drive the real MCP server object rather than spawning it, so the
# orchestrator's session handling runs for real without a subprocess or a socket.
MCP_SERVER_DIR = Path(__file__).resolve().parents[2] / "mcp-server"
if str(MCP_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_SERVER_DIR))


@pytest.fixture
def live_mcp(monkeypatch: pytest.MonkeyPatch) -> Generator[Any, None, None]:
    """Point the orchestrator at an in-process MCP server."""
    import claude as mcp_claude
    import server as mcp_server

    from agent import orchestrator

    instance = mcp_server.build_server()
    monkeypatch.setattr(orchestrator, "_mcp_target", lambda: instance)
    yield instance
    mcp_claude.set_client(None)
