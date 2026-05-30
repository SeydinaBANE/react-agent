from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from agent.core.schemas import AgentStep, StepEvent, TaskTrace
from agent.core.telemetry import get_logger

logger = get_logger(__name__)


class Tracer:
    """Collects AgentSteps and fans them out to SSE subscribers."""

    def __init__(self, trace: TaskTrace) -> None:
        self._trace = trace
        self._queues: list[asyncio.Queue[StepEvent | None]] = []

    def subscribe(self) -> asyncio.Queue[StepEvent | None]:
        """Return a queue that will receive StepEvents as they happen.

        Caller must drain the queue; a None sentinel signals stream end.
        """
        q: asyncio.Queue[StepEvent | None] = asyncio.Queue()
        self._queues.append(q)
        return q

    def record_step(self, step: AgentStep) -> None:
        # WorkingMemory.append_step owns the trace mutation; tracer only fans out events.
        event = StepEvent(event="step", data=step)
        for q in self._queues:
            q.put_nowait(event)
        logger.debug("step_recorded", iteration=step.iteration, tool=step.action.tool)

    def record_final(self, answer: str) -> None:
        event = StepEvent(event="final", data=answer)
        for q in self._queues:
            q.put_nowait(event)
            q.put_nowait(None)  # sentinel

    def record_error(self, message: str) -> None:
        event = StepEvent(event="error", data=message)
        for q in self._queues:
            q.put_nowait(event)
            q.put_nowait(None)

    def record_waiting_approval(self, tool_name: str) -> None:
        event = StepEvent(event="waiting_approval", data=f"Waiting for approval: {tool_name}")
        for q in self._queues:
            q.put_nowait(event)

    async def stream(self, queue: asyncio.Queue[StepEvent | None]) -> AsyncIterator[str]:
        """Async generator that yields SSE-formatted strings until stream ends."""
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event.to_sse()

    def export_json(self) -> str:
        return self._trace.model_dump_json(indent=2)
