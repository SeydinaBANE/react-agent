from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM (OpenRouter) ─────────────────────────────────────────────────────
    openrouter_api_key: str = Field(..., min_length=10)
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    agent_model: str = "anthropic/claude-haiku-4.5"

    # ── Brave Search ─────────────────────────────────────────────────────────
    brave_api_key: str = ""

    # ── Qdrant ───────────────────────────────────────────────────────────────
    qdrant_host: str = "localhost"
    qdrant_port: int = Field(default=6333, ge=1, le=65535)
    qdrant_collection: str = "agent_memory"

    # ── API auth ─────────────────────────────────────────────────────────────
    jwt_secret_key: str = Field(..., min_length=32)
    jwt_algorithm: str = "HS256"
    api_rate_limit: str = "60/minute"

    # ── Agent behavior ───────────────────────────────────────────────────────
    agent_max_iterations: int = Field(default=15, ge=1, le=50)
    agent_tool_timeout: int = Field(default=10, ge=1, le=120)
    agent_code_executor_enabled: bool = True

    # ── Observability ────────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_format: str = "json"
    prometheus_enabled: bool = True

    # ── File I/O ─────────────────────────────────────────────────────────────
    file_io_allowed_paths: str = "/tmp,/workspace"  # noqa: S108

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return upper

    @field_validator("log_format")
    @classmethod
    def validate_log_format(cls, v: str) -> str:
        allowed = {"json", "pretty"}
        lower = v.lower()
        if lower not in allowed:
            raise ValueError(f"log_format must be one of {allowed}")
        return lower

    @property
    def file_io_allowed_paths_list(self) -> list[str]:
        return [p.strip() for p in self.file_io_allowed_paths.split(",") if p.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
