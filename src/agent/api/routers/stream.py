from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from agent.core.schemas import StepEvent
from agent.core.telemetry import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/tasks", tags=["stream"])

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@router.get("/{task_id}/stream")
async def stream_task(task_id: str, request: Request) -> StreamingResponse:
    """Stream agent steps as Server-Sent Events until task completes."""
    tracer_registry = request.app.state.tracer_registry
    tracer = tracer_registry.get(task_id)

    if tracer is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")

    # If the task already finished, replay the terminal event immediately instead of
    # blocking forever on a queue that will never receive a sentinel.
    if tracer.trace.is_terminal():
        answer = tracer.trace.final_answer or ""
        event_type: Literal["final", "error"] = (
            "final" if tracer.trace.status == "completed" else "error"
        )

        async def _replay() -> AsyncIterator[str]:
            yield StepEvent(event=event_type, data=answer).to_sse()

        return StreamingResponse(_replay(), media_type="text/event-stream", headers=_SSE_HEADERS)

    queue = tracer.subscribe()

    async def event_generator() -> AsyncIterator[str]:
        try:
            async for chunk in tracer.stream(queue):
                if await request.is_disconnected():
                    break
                yield chunk
        except Exception:
            logger.exception("stream_error", task_id=task_id)

    return StreamingResponse(
        event_generator(), media_type="text/event-stream", headers=_SSE_HEADERS
    )
