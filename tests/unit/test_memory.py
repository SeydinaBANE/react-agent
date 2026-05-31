"""Tests for memory module (Qdrant and embedder mocked)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.core.exceptions import MemoryError as AgentMemoryError
from agent.core.schemas import Action, AgentStep, TaskTrace
from agent.memory.working import WorkingMemory

# ── WorkingMemory ─────────────────────────────────────────────────────────────


class TestWorkingMemory:
    def _make_wm(self, goal: str = "test goal") -> WorkingMemory:
        trace = TaskTrace(goal=goal)
        return WorkingMemory(trace)

    def test_initial_iteration_is_zero(self) -> None:
        wm = self._make_wm()
        assert wm.iteration == 0

    def test_append_step_increments_iteration(self) -> None:
        wm = self._make_wm()
        step = AgentStep(
            iteration=1,
            thought="thinking",
            action=Action(tool="web_search", input={}),
            observation="result",
            latency_ms=100,
        )
        wm.append_step(step)
        assert wm.iteration == 1

    def test_set_final_answer_completes_task(self) -> None:
        wm = self._make_wm()
        wm.set_final_answer("The answer is 42")
        assert wm.status == "completed"
        assert wm.trace.final_answer == "The answer is 42"
        assert wm.trace.completed_at is not None

    def test_set_failed_marks_task_failed(self) -> None:
        wm = self._make_wm()
        wm.set_failed("Max iterations reached")
        assert wm.status == "failed"
        assert "FAILED" in (wm.trace.final_answer or "")

    def test_steps_returns_copy(self) -> None:
        wm = self._make_wm()
        steps = wm.steps
        steps.append(MagicMock())  # mutating the returned list should not affect wm
        assert wm.iteration == 0


# ── EpisodicMemory (Qdrant mocked) ────────────────────────────────────────────


class TestEpisodicMemory:
    @pytest.fixture
    def mock_embedder(self) -> MagicMock:
        embedder = MagicMock()
        embedder.dim = 384
        embedder.embed = AsyncMock(return_value=[0.1] * 384)
        return embedder

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        client = MagicMock()
        client.get_collections = AsyncMock(return_value=MagicMock(collections=[]))
        client.create_collection = AsyncMock()
        client.upsert = AsyncMock()
        scored = MagicMock()
        scored.payload = {"text": "past observation about RAG"}
        query_result = MagicMock()
        query_result.points = [scored]
        client.query_points = AsyncMock(return_value=query_result)
        client.delete = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_ensure_collection_creates_if_missing(
        self, mock_client: MagicMock, mock_embedder: MagicMock
    ) -> None:
        from agent.memory.episodic import EpisodicMemory

        memory = EpisodicMemory(mock_client, mock_embedder, "test_col")
        await memory.ensure_collection()
        mock_client.create_collection.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_returns_point_id(
        self, mock_client: MagicMock, mock_embedder: MagicMock
    ) -> None:
        from agent.memory.episodic import EpisodicMemory

        memory = EpisodicMemory(mock_client, mock_embedder, "test_col")
        pid = await memory.store("This is an observation")
        assert isinstance(pid, str) and len(pid) > 0
        mock_client.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_returns_text(
        self, mock_client: MagicMock, mock_embedder: MagicMock
    ) -> None:
        from agent.memory.episodic import EpisodicMemory

        memory = EpisodicMemory(mock_client, mock_embedder, "test_col")
        results = await memory.search("RAG papers")
        assert len(results) == 1
        assert "past observation" in results[0]

    @pytest.mark.asyncio
    async def test_store_raises_on_qdrant_error(
        self, mock_client: MagicMock, mock_embedder: MagicMock
    ) -> None:
        from agent.memory.episodic import EpisodicMemory

        mock_client.upsert = AsyncMock(side_effect=Exception("Qdrant down"))
        memory = EpisodicMemory(mock_client, mock_embedder, "test_col")
        with pytest.raises(AgentMemoryError):
            await memory.store("some text")
