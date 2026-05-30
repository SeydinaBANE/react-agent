"""Tests for telemetry: correlation IDs and structlog setup."""
from __future__ import annotations

from agent.core.telemetry import get_correlation_id, set_correlation_id


class TestCorrelationId:
    def test_get_generates_id_if_missing(self) -> None:
        set_correlation_id("")
        cid = get_correlation_id()
        assert len(cid) == 36  # UUID4 format

    def test_set_and_get(self) -> None:
        set_correlation_id("my-custom-id")
        assert get_correlation_id() == "my-custom-id"

    def test_different_values_after_reset(self) -> None:
        set_correlation_id("")
        cid1 = get_correlation_id()
        set_correlation_id("")
        cid2 = get_correlation_id()
        # Each empty reset generates a new UUID
        assert cid1 != cid2
