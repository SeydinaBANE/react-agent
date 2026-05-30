"""Tests for core schemas."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent.core.schemas import (
    Action,
    AgentStep,
    ApproveActionRequest,
    CreateTaskRequest,
    ProblemDetail,
    StepEvent,
    TaskTrace,
)


class TestAction:
    def test_defaults(self) -> None:
        action = Action(tool="web_search", input={"query": "test"})
        assert action.is_destructive is False

    def test_destructive_flag(self) -> None:
        action = Action(tool="file_io", input={"path": "/tmp/x"}, is_destructive=True)
        assert action.is_destructive is True


class TestTaskTrace:
    def test_initial_status_is_running(self) -> None:
        trace = TaskTrace(goal="test goal")
        assert trace.status == "running"
        assert trace.final_answer is None
        assert trace.steps == []

    def test_task_id_is_generated(self) -> None:
        t1 = TaskTrace(goal="a")
        t2 = TaskTrace(goal="b")
        assert t1.task_id != t2.task_id

    def test_is_terminal_running(self) -> None:
        trace = TaskTrace(goal="test")
        assert trace.is_terminal() is False

    def test_is_terminal_completed(self) -> None:
        trace = TaskTrace(goal="test", status="completed")
        assert trace.is_terminal() is True

    def test_is_terminal_failed(self) -> None:
        trace = TaskTrace(goal="test", status="failed")
        assert trace.is_terminal() is True

    def test_is_not_terminal_waiting_approval(self) -> None:
        trace = TaskTrace(goal="test", status="waiting_approval")
        assert trace.is_terminal() is False


class TestAgentStep:
    def test_valid_step(self) -> None:
        step = AgentStep(
            iteration=1,
            thought="I need to search",
            action=Action(tool="web_search", input={"query": "RAG papers"}),
            observation="Found 5 papers",
            latency_ms=250,
        )
        assert step.iteration == 1
        assert isinstance(step.timestamp, datetime)

    def test_iteration_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            AgentStep(
                iteration=0,
                thought="t",
                action=Action(tool="x", input={}),
                observation="o",
                latency_ms=0,
            )


class TestCreateTaskRequest:
    def test_empty_goal_rejected(self) -> None:
        with pytest.raises(ValueError):
            CreateTaskRequest(goal="")

    def test_too_long_goal_rejected(self) -> None:
        with pytest.raises(ValueError):
            CreateTaskRequest(goal="x" * 2001)


class TestStepEvent:
    def test_to_sse_format(self) -> None:
        step = AgentStep(
            iteration=1,
            thought="thinking",
            action=Action(tool="web_search", input={}),
            observation="result",
            latency_ms=100,
        )
        event = StepEvent(event="step", data=step)
        sse = event.to_sse()
        assert sse.startswith("event: step\n")
        assert sse.endswith("\n\n")


class TestProblemDetail:
    def test_defaults(self) -> None:
        p = ProblemDetail(title="Not Found", status=404, detail="Resource missing")
        assert p.type == "about:blank"
        assert p.instance == ""
