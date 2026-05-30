"""Tests for ReactLoop, ApprovalGate, and Tracer."""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.core.schemas import Action, AgentStep, TaskTrace
from agent.runner.approval_gate import ApprovalGate
from agent.runner.tracer import Tracer


# ── Tracer ────────────────────────────────────────────────────────────────────

class TestTracer:
    def _make_step(self, iteration: int = 1) -> AgentStep:
        return AgentStep(
            iteration=iteration,
            thought="thinking",
            action=Action(tool="web_search", input={}),
            observation="result",
            latency_ms=100,
        )

    def test_record_step_broadcasts_event(self) -> None:
        trace = TaskTrace(goal="test")
        tracer = Tracer(trace)
        queue = tracer.subscribe()
        tracer.record_step(self._make_step())
        assert not queue.empty()  # event was broadcast
        assert len(trace.steps) == 0  # trace mutation is WorkingMemory's responsibility

    def test_subscriber_receives_step_event(self) -> None:
        trace = TaskTrace(goal="test")
        tracer = Tracer(trace)
        queue = tracer.subscribe()
        tracer.record_step(self._make_step())
        event = queue.get_nowait()
        assert event is not None
        assert event.event == "step"

    def test_record_final_sends_sentinel(self) -> None:
        trace = TaskTrace(goal="test")
        tracer = Tracer(trace)
        queue = tracer.subscribe()
        tracer.record_final("The answer")
        event = queue.get_nowait()
        sentinel = queue.get_nowait()
        assert event is not None and event.event == "final"
        assert sentinel is None

    def test_export_json_is_valid(self) -> None:
        import json

        trace = TaskTrace(goal="test")
        tracer = Tracer(trace)
        json_str = tracer.export_json()
        data = json.loads(json_str)
        assert data["goal"] == "test"

    @pytest.mark.asyncio
    async def test_stream_yields_sse_strings(self) -> None:
        trace = TaskTrace(goal="test")
        tracer = Tracer(trace)
        queue = tracer.subscribe()

        tracer.record_step(self._make_step(1))
        tracer.record_final("done")

        chunks = []
        async for chunk in tracer.stream(queue):
            chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0].startswith("event: step")
        assert chunks[1].startswith("event: final")


# ── ApprovalGate ──────────────────────────────────────────────────────────────

class TestApprovalGate:
    @pytest.mark.asyncio
    async def test_non_destructive_action_passes(self) -> None:
        gate = ApprovalGate()
        action = Action(tool="web_search", input={}, is_destructive=False)
        await gate.check("task-1", action)  # should not raise

    @pytest.mark.asyncio
    async def test_destructive_action_raises(self) -> None:
        from agent.core.exceptions import HumanApprovalRequired

        gate = ApprovalGate()
        action = Action(tool="file_io", input={}, is_destructive=True)
        with pytest.raises(HumanApprovalRequired):
            await gate.check("task-1", action)

    @pytest.mark.asyncio
    async def test_resolve_approved_unblocks_wait(self) -> None:
        gate = ApprovalGate()

        async def approve_after_delay() -> None:
            await asyncio.sleep(0.01)
            gate.resolve("task-2", approved=True)

        asyncio.create_task(approve_after_delay())
        approved = await gate.wait("task-2")
        assert approved is True

    @pytest.mark.asyncio
    async def test_resolve_rejected_returns_false(self) -> None:
        gate = ApprovalGate()

        async def reject_after_delay() -> None:
            await asyncio.sleep(0.01)
            gate.resolve("task-3", approved=False)

        asyncio.create_task(reject_after_delay())
        approved = await gate.wait("task-3")
        assert approved is False


# ── ReactLoop ─────────────────────────────────────────────────────────────────

def _make_mock_llm(
    responses: list[tuple[str, str, dict[str, Any]]],
) -> MagicMock:
    """responses: list of (thought, tool_name, tool_input)"""
    from agent.core.schemas import Action

    calls = iter(responses)

    async def mock_call(**kwargs: Any) -> tuple[str, Action]:
        thought, tool, inp = next(calls)
        return thought, Action(tool=tool, input=inp)

    llm = MagicMock()
    llm.call = mock_call
    return llm


class TestReactLoop:
    @pytest.fixture
    def mock_memory(self) -> MagicMock:
        m = MagicMock()
        m.search = AsyncMock(return_value=[])
        m.store = AsyncMock(return_value="point-id")
        return m

    @pytest.fixture
    def mock_registry(self) -> MagicMock:
        tool = MagicMock()
        tool.execute = AsyncMock(return_value="tool result")
        tool.to_anthropic_schema.return_value = {"name": "web_search", "description": "search", "input_schema": {}}

        registry = MagicMock()
        registry.get.return_value = tool
        registry.all_schemas.return_value = [{"name": "web_search", "description": "search", "input_schema": {}}]
        return registry

    @pytest.mark.asyncio
    async def test_single_step_then_final_answer(
        self, mock_memory: MagicMock, mock_registry: MagicMock
    ) -> None:
        from agent.runner.approval_gate import ApprovalGate
        from agent.runner.react_loop import ReactLoop
        from agent.runner.tracer import Tracer

        llm = _make_mock_llm([
            ("Let me search", "web_search", {"query": "test"}),
            ("I have the answer", "final_answer", {"answer": "42"}),
        ])

        loop = ReactLoop(
            llm=llm,
            registry=mock_registry,
            memory=mock_memory,
            gate=ApprovalGate(),
            max_iterations=10,
        )
        trace = TaskTrace(goal="What is 6 x 7?")
        tracer = Tracer(trace)

        wm = await loop.run(trace, tracer)

        assert wm.status == "completed"
        assert wm.trace.final_answer == "42"
        assert wm.iteration == 1

    @pytest.mark.asyncio
    async def test_max_iterations_marks_failed(
        self, mock_memory: MagicMock, mock_registry: MagicMock
    ) -> None:
        from agent.runner.approval_gate import ApprovalGate
        from agent.runner.react_loop import ReactLoop
        from agent.runner.tracer import Tracer

        # Always returns a non-final tool call → will hit max
        llm = _make_mock_llm(
            [("thinking", "web_search", {"query": "x"})] * 5
        )

        loop = ReactLoop(
            llm=llm,
            registry=mock_registry,
            memory=mock_memory,
            gate=ApprovalGate(),
            max_iterations=3,
        )
        trace = TaskTrace(goal="loop forever")
        tracer = Tracer(trace)

        wm = await loop.run(trace, tracer)
        assert wm.status == "failed"
        assert "FAILED" in (wm.trace.final_answer or "")
