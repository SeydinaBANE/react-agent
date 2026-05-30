"""Tests for settings / configuration."""
from __future__ import annotations

import pytest

from agent.core.config import Settings


class TestSettings:
    def test_defaults_with_required_fields(self) -> None:
        s = Settings(
            openrouter_api_key="sk-or-test-key",
            jwt_secret_key="a" * 32,
            log_format="json",  # conftest sets LOG_FORMAT=pretty via env
        )
        assert s.agent_max_iterations == 15
        assert s.log_level == "INFO"
        assert s.log_format == "json"
        assert s.qdrant_port == 6333

    def test_log_level_uppercased(self) -> None:
        s = Settings(
            openrouter_api_key="sk-or-test-key",
            jwt_secret_key="a" * 32,
            log_level="debug",
        )
        assert s.log_level == "DEBUG"

    def test_invalid_log_level_rejected(self) -> None:
        with pytest.raises(ValueError):
            Settings(
                openrouter_api_key="sk-or-test-key",
                jwt_secret_key="a" * 32,
                log_level="VERBOSE",
            )

    def test_invalid_log_format_rejected(self) -> None:
        with pytest.raises(ValueError):
            Settings(
                openrouter_api_key="sk-or-test-key",
                jwt_secret_key="a" * 32,
                log_format="xml",
            )

    def test_short_jwt_secret_rejected(self) -> None:
        with pytest.raises(ValueError):
            Settings(
                openrouter_api_key="sk-or-test-key",
                jwt_secret_key="short",
            )

    def test_file_io_allowed_paths_list(self) -> None:
        s = Settings(
            openrouter_api_key="sk-or-test-key",
            jwt_secret_key="a" * 32,
            file_io_allowed_paths="/tmp, /workspace , /data",
        )
        assert s.file_io_allowed_paths_list == ["/tmp", "/workspace", "/data"]
