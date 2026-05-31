from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ── Tool action ───────────────────────────────────────────────────────────────


class Action(BaseModel):
    tool: str
    input: dict[str, Any]
    is_destructive: bool = False


# ── Agent step (one ReAct iteration) ─────────────────────────────────────────


class AgentStep(BaseModel):
    iteration: int = Field(..., ge=1)
    thought: str
    action: Action
    observation: str
    latency_ms: int = Field(..., ge=0)
    timestamp: datetime = Field(default_factory=_utcnow)


# ── Task status ───────────────────────────────────────────────────────────────

TaskStatus = Literal["running", "waiting_approval", "completed", "failed"]


# ── Full task trace ───────────────────────────────────────────────────────────


class TaskTrace(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    goal: str
    steps: list[AgentStep] = Field(default_factory=list)
    final_answer: str | None = None
    status: TaskStatus = "running"
    created_at: datetime = Field(default_factory=_utcnow)
    completed_at: datetime | None = None

    def is_terminal(self) -> bool:
        return self.status in {"completed", "failed"}


# ── API request / response ────────────────────────────────────────────────────


class CreateTaskRequest(BaseModel):
    goal: str = Field(..., min_length=1, max_length=2000)


class ApproveActionRequest(BaseModel):
    approved: bool
    reason: str = ""


class TaskSummary(BaseModel):
    task_id: str
    goal: str
    status: TaskStatus
    iterations: int
    created_at: datetime
    completed_at: datetime | None


# ── SSE event ─────────────────────────────────────────────────────────────────


class StepEvent(BaseModel):
    event: Literal["step", "final", "error", "waiting_approval"] = "step"
    data: AgentStep | str

    def to_sse(self) -> str:
        return f"event: {self.event}\ndata: {self.model_dump_json()}\n\n"


# ── RFC 7807 problem details ──────────────────────────────────────────────────


class ProblemDetail(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str = ""
