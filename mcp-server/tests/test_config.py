"""The MCP server resolves the photo directory the same way the API does."""

from __future__ import annotations

from pathlib import Path

import pytest

import config as config_module
from config import McpSettings

SERVER_ROOT = Path(config_module.__file__).resolve().parents[1]


def test_relative_upload_dir_is_anchored_not_cwd_relative(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The MCP server reads photos the API wrote, so both must agree on the path
    regardless of which directory each process was started from."""
    monkeypatch.chdir(tmp_path)
    settings = McpSettings(upload_dir=Path("./uploads"))
    assert settings.upload_dir == SERVER_ROOT / "uploads"
    assert settings.upload_dir.is_absolute()


def test_an_absolute_upload_dir_is_left_alone(tmp_path: Path) -> None:
    assert McpSettings(upload_dir=tmp_path / "blobs").upload_dir == tmp_path / "blobs"
