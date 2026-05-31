from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse

from agent.core.schemas import (
    ApproveActionRequest,
    CreateTaskRequest,
    TaskSummary,
    TaskTrace,
)
from agent.core.telemetry import TASK_CREATED, get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])

# In-process task store: task_id → TaskTrace
# Production: swap for a Redis/DB backend
_task_store: dict[str, TaskTrace] = {}


def get_task_store() -> dict[str, TaskTrace]:
    return _task_store


@router.post("", status_code=202, response_model=TaskSummary)
async def create_task(
    body: CreateTaskRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> TaskSummary:
    """Submit a new goal to the agent. Returns immediately; execution is async."""
    from agent.core.schemas import TaskTrace

    trace = TaskTrace(goal=body.goal)
    _task_store[trace.task_id] = trace
    TASK_CREATED.inc()

    # Launch the ReAct loop in the background
    from agent.runner.tracer import Tracer

    react_loop = request.app.state.react_loop
    tracer_registry = request.app.state.tracer_registry
    tracer = Tracer(trace)
    tracer_registry[trace.task_id] = tracer

    background_tasks.add_task(_run_task, react_loop, trace, tracer)

    logger.info("task_created", task_id=trace.task_id, goal=body.goal[:80])
    return TaskSummary(
        task_id=trace.task_id,
        goal=trace.goal,
        status=trace.status,
        iterations=0,
        created_at=trace.created_at,
        completed_at=trace.completed_at,
    )


async def _run_task(react_loop: object, trace: TaskTrace, tracer: object) -> None:
    from agent.runner.react_loop import ReactLoop as _ReactLoop
    from agent.runner.tracer import Tracer as _Tracer

    assert isinstance(react_loop, _ReactLoop)
    assert isinstance(tracer, _Tracer)
    await react_loop.run(trace, tracer)


@router.get("/{task_id}", response_model=TaskSummary)
async def get_task(task_id: str) -> TaskSummary:
    trace = _get_trace_or_404(task_id)
    return TaskSummary(
        task_id=trace.task_id,
        goal=trace.goal,
        status=trace.status,
        iterations=len(trace.steps),
        created_at=trace.created_at,
        completed_at=trace.completed_at,
    )


@router.get("/{task_id}/trace", response_model=TaskTrace)
async def get_trace(task_id: str) -> TaskTrace:
    return _get_trace_or_404(task_id)


@router.post("/{task_id}/approve", status_code=200)
async def approve_action(
    task_id: str, body: ApproveActionRequest, request: Request
) -> JSONResponse:
    """Approve or reject a pending destructive action for a task."""
    trace = _get_trace_or_404(task_id)
    if trace.status != "waiting_approval":
        raise HTTPException(status_code=409, detail="Task is not waiting for approval.")

    gate = request.app.state.approval_gate
    gate.resolve(task_id, approved=body.approved)
    return JSONResponse({"approved": body.approved, "task_id": task_id})


def _get_trace_or_404(task_id: str) -> TaskTrace:
    trace = _task_store.get(task_id)
    if trace is None:
        raise HTTPException(
            status_code=404,
            detail=f"Task '{task_id}' not found.",
        )
    return trace
