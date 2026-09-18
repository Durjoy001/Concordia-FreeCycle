"""Orchestrator settings - same env vars as the API, read independently."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    agent_max_retries: int = 3
    agent_retry_base_delay: float = 0.5
    agent_max_tool_iterations: int = 6
    agent_request_timeout: float = 90.0
    agent_max_tokens: int = 4096

    mcp_transport: str = "http"
    mcp_server_url: str = "http://localhost:8765/mcp"
    mcp_server_command: str = "python"
    mcp_server_args: str = "mcp-server/server.py --transport stdio"

    @property
    def mcp_server_arg_list(self) -> list[str]:
        return self.mcp_server_args.split()


@lru_cache
def get_settings() -> AgentSettings:
    return AgentSettings()
