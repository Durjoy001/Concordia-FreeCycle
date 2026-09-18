"""Environment-driven application settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from the environment (see .env.example)."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Database ---
    database_url: str = "postgresql+psycopg://freecycle:freecycle@localhost:5432/freecycle"

    # --- Auth ---
    jwt_secret: str = "dev-only-insecure-secret-please-change-me-now"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14

    # --- Agent layer ---
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    agent_daily_budget: int = 20
    agent_enabled: bool = True
    agent_max_retries: int = 3
    match_score_threshold: float = 0.6

    # --- MCP server ---
    mcp_transport: str = "http"
    mcp_server_url: str = "http://localhost:8765/mcp"
    mcp_server_command: str = "python"
    mcp_server_args: str = "mcp-server/server.py --transport stdio"

    # --- Storage ---
    upload_dir: Path = Path("./uploads")
    public_upload_base_url: str = "/uploads"
    max_upload_bytes: int = 8 * 1024 * 1024
    api_prefix: str = "/api/v1"

    # --- CORS ---
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @field_validator("jwt_secret")
    @classmethod
    def _check_secret_length(cls, value: str) -> str:
        # HS256 keys shorter than the 32-byte hash output weaken the signature
        # (RFC 7518 s.3.2); PyJWT warns, we refuse to boot.
        if len(value.encode("utf-8")) < 32:
            raise ValueError("JWT_SECRET must be at least 32 bytes long")
        return value

    @field_validator("mcp_transport")
    @classmethod
    def _check_transport(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"http", "stdio"}:
            raise ValueError("MCP_TRANSPORT must be 'http' or 'stdio'")
        return normalized

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def mcp_server_arg_list(self) -> list[str]:
        return self.mcp_server_args.split()

    @property
    def agent_configured(self) -> bool:
        """The agent layer is only usable with a key, a budget and the feature flag on."""
        return bool(self.agent_enabled and self.anthropic_api_key and self.agent_daily_budget > 0)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
