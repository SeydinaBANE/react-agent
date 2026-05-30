"""Tests for FastAPI endpoints (all external services mocked)."""
from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _build_mock_state() -> tuple[MagicMock, MagicMock, dict[str, Any]]:
    """Return (mock_react_loop, mock_gate, tracer_registry)."""
    gate = MagicMock()
    gate.resolve = MagicMock()
    react_loop = MagicMock()
    react_loop.run = AsyncMock()
    return react_loop, gate, {}


@pytest.fixture
def client() -> Iterator[TestClient]:
    from agent.core.config import Settings
    from agent.api.main import create_app

    test_settings = Settings(
        openrouter_api_key="sk-or-test-key",
        jwt_secret_key="test-secret-key-minimum-32-chars-!!",
        log_format="pretty",
    )
    react_loop, gate, tracer_reg = _build_mock_state()

    @asynccontextmanager
    async def test_lifespan(app: Any) -> AsyncIterator[None]:
        app.state.react_loop = react_loop
        app.state.approval_gate = gate
        app.state.tracer_registry = tracer_reg
        yield

    with patch("agent.api.main.get_settings", return_value=test_settings):
        with patch("agent.api.main.lifespan", test_lifespan):
            app = create_app()

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _auth_header() -> dict[str, str]:
    from jose import jwt

    token = jwt.encode(
        {"sub": "test-user"},
        "test-secret-key-minimum-32-chars-!!",
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


# ── Health endpoints ──────────────────────────────────────────────────────────

class TestHealthEndpoints:
    def test_health_returns_ok(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_ready_returns_ready(self, client: TestClient) -> None:
        resp = client.get("/ready")
        assert resp.status_code == 200


# ── Task CRUD ─────────────────────────────────────────────────────────────────

class TestTaskEndpoints:
    def test_create_task_returns_202(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/tasks",
            json={"goal": "Research RAG papers"},
            headers=_auth_header(),
        )
        assert resp.status_code == 202
        data = resp.json()
        assert "task_id" in data
        assert data["status"] == "running"

    def test_get_task_returns_summary(self, client: TestClient) -> None:
        create_resp = client.post(
            "/api/v1/tasks",
            json={"goal": "test goal"},
            headers=_auth_header(),
        )
        task_id = create_resp.json()["task_id"]
        get_resp = client.get(f"/api/v1/tasks/{task_id}", headers=_auth_header())
        assert get_resp.status_code == 200
        assert get_resp.json()["task_id"] == task_id

    def test_get_nonexistent_task_returns_404(self, client: TestClient) -> None:
        resp = client.get("/api/v1/tasks/nope", headers=_auth_header())
        assert resp.status_code == 404

    def test_get_trace_returns_full_trace(self, client: TestClient) -> None:
        create_resp = client.post(
            "/api/v1/tasks",
            json={"goal": "trace test"},
            headers=_auth_header(),
        )
        task_id = create_resp.json()["task_id"]
        trace_resp = client.get(f"/api/v1/tasks/{task_id}/trace", headers=_auth_header())
        assert trace_resp.status_code == 200
        assert trace_resp.json()["goal"] == "trace test"

    def test_empty_goal_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/tasks",
            json={"goal": ""},
            headers=_auth_header(),
        )
        assert resp.status_code == 422

    def test_unauthenticated_request_returns_401(self, client: TestClient) -> None:
        resp = client.post("/api/v1/tasks", json={"goal": "test"})
        assert resp.status_code == 401

    def test_approve_non_waiting_task_returns_409(self, client: TestClient) -> None:
        create_resp = client.post(
            "/api/v1/tasks",
            json={"goal": "approve test"},
            headers=_auth_header(),
        )
        task_id = create_resp.json()["task_id"]
        approve_resp = client.post(
            f"/api/v1/tasks/{task_id}/approve",
            json={"approved": True},
            headers=_auth_header(),
        )
        assert approve_resp.status_code == 409
