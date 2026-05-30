from __future__ import annotations

from agent.core.schemas import AgentStep, TaskStatus, TaskTrace


class WorkingMemory:
    """In-process mutable state for the current task execution.

    Wraps a TaskTrace and provides a clean interface for the runner.
    Not persisted — lives only for the duration of one task.
    """

    def __init__(self, trace: TaskTrace) -> None:
        self._trace = trace

    # ── Accessors ─────────────────────────────────────────────────────────────

    @property
    def task_id(self) -> str:
        return self._trace.task_id

    @property
    def goal(self) -> str:
        return self._trace.goal

    @property
    def status(self) -> TaskStatus:
        return self._trace.status

    @property
    def steps(self) -> list[AgentStep]:
        return list(self._trace.steps)

    @property
    def iteration(self) -> int:
        return len(self._trace.steps)

    @property
    def trace(self) -> TaskTrace:
        return self._trace

    # ── Mutations ─────────────────────────────────────────────────────────────

    def append_step(self, step: AgentStep) -> None:
        self._trace.steps.append(step)

    def set_status(self, status: TaskStatus) -> None:
        self._trace.status = status

    def set_final_answer(self, answer: str) -> None:
        from datetime import datetime, timezone

        self._trace.final_answer = answer
        self._trace.status = "completed"
        self._trace.completed_at = datetime.now(timezone.utc)

    def set_failed(self, reason: str) -> None:
        from datetime import datetime, timezone

        self._trace.final_answer = f"[FAILED] {reason}"
        self._trace.status = "failed"
        self._trace.completed_at = datetime.now(timezone.utc)
