"""Shared pytest fixtures for all test levels."""
from __future__ import annotations

import os
from collections.abc import Generator

import pytest

# Set dummy env vars before any module import triggers settings validation
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy-key-1234567890")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-minimum-32-characters-long")
os.environ.setdefault("QDRANT_HOST", "localhost")
os.environ.setdefault("LOG_FORMAT", "pretty")


@pytest.fixture(autouse=True)
def reset_lru_cache() -> Generator[None, None, None]:
    """Reset settings cache between tests so env overrides take effect."""
    from agent.core.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
