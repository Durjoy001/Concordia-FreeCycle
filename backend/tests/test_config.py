"""Settings behaviour that is easy to get wrong and invisible until it bites."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.config as config_module
from app.config import Settings

REPO_ROOT = Path(config_module.__file__).resolve().parents[2]
VALID_SECRET = "a" * 32


def test_relative_upload_dir_is_anchored_to_the_repo_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The photo directory must not depend on where the process was launched.

    Regression: uvicorn is normally started from backend/, so a relative
    "./uploads" resolved to backend/uploads for the API while anything run from
    the repo root wrote to ./uploads. The static mount then served a directory
    nothing was writing to, and every photo 404'd.
    """
    monkeypatch.chdir(tmp_path)
    settings = Settings(upload_dir=Path("./uploads"), jwt_secret=VALID_SECRET)
    assert settings.upload_dir == REPO_ROOT / "uploads"
    assert settings.upload_dir.is_absolute()


def test_upload_dir_is_the_same_from_any_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    from_root = Settings(upload_dir=Path("uploads"), jwt_secret=VALID_SECRET).upload_dir
    monkeypatch.chdir(tmp_path)
    from_elsewhere = Settings(upload_dir=Path("uploads"), jwt_secret=VALID_SECRET).upload_dir
    # Both absolute, or two unresolved relative paths would compare equal while
    # still pointing at different directories - which is the bug this guards.
    assert from_root.is_absolute() and from_elsewhere.is_absolute()
    assert from_root == from_elsewhere == REPO_ROOT / "uploads"


def test_an_absolute_upload_dir_is_left_alone(tmp_path: Path) -> None:
    """Docker sets an absolute /srv/uploads; that must pass through untouched."""
    settings = Settings(upload_dir=tmp_path / "blobs", jwt_secret=VALID_SECRET)
    assert settings.upload_dir == tmp_path / "blobs"


def test_short_jwt_secret_is_refused_at_startup() -> None:
    with pytest.raises(ValueError, match="at least 32 bytes"):
        Settings(jwt_secret="too-short")


def test_agent_is_only_configured_with_a_key_a_flag_and_a_budget() -> None:
    base = {"jwt_secret": VALID_SECRET, "anthropic_api_key": "sk-ant-test"}
    assert Settings(**base, agent_enabled=True, agent_daily_budget=20).agent_configured
    assert not Settings(**base, agent_enabled=False, agent_daily_budget=20).agent_configured
    assert not Settings(**base, agent_enabled=True, agent_daily_budget=0).agent_configured
    assert not Settings(
        jwt_secret=VALID_SECRET, anthropic_api_key="", agent_enabled=True, agent_daily_budget=20
    ).agent_configured
