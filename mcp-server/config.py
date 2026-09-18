"""MCP server settings - independent of the FastAPI app, same env vars."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class McpSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+psycopg://freecycle:freecycle@localhost:5432/freecycle"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    match_score_threshold: float = 0.6
    upload_dir: Path = Path("./uploads")
    max_wishlist_candidates: int = 200
    request_timeout_seconds: float = 90.0


@lru_cache
def get_settings() -> McpSettings:
    return McpSettings()
