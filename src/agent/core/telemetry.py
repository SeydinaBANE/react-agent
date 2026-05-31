from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

import structlog
from prometheus_client import Counter, Gauge, Histogram

# ── Correlation ID ────────────────────────────────────────────────────────────

_correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    cid = _correlation_id_var.get()
    if not cid:
        cid = str(uuid4())
        _correlation_id_var.set(cid)
    return cid


def set_correlation_id(cid: str) -> None:
    _correlation_id_var.set(cid)


def _add_correlation_id(
    logger: Any,  # noqa: ANN401
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    event_dict["correlation_id"] = get_correlation_id()
    return event_dict


# ── Structlog setup ───────────────────────────────────────────────────────────


def configure_logging(log_level: str = "INFO", log_format: str = "json") -> None:
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        _add_correlation_id,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.ExceptionRenderer(),
    ]

    if log_format == "pretty":
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(log_level)),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]


# ── Prometheus metrics ────────────────────────────────────────────────────────

TASK_CREATED = Counter(
    "agent_tasks_created_total",
    "Total number of agent tasks submitted",
)

TASK_STATUS = Counter(
    "agent_tasks_status_total",
    "Task outcomes by status",
    ["status"],
)

REACT_ITERATIONS = Histogram(
    "agent_react_iterations",
    "Number of ReAct iterations per completed task",
    buckets=[1, 2, 3, 5, 7, 10, 15, 20],
)

TOOL_CALLS = Counter(
    "agent_tool_calls_total",
    "Tool invocations by tool name and outcome",
    ["tool", "outcome"],
)

TOOL_LATENCY = Histogram(
    "agent_tool_latency_seconds",
    "Tool execution latency",
    ["tool"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

LLM_LATENCY = Histogram(
    "agent_llm_latency_seconds",
    "LLM call latency",
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

APPROVAL_PENDING = Gauge(
    "agent_approvals_pending",
    "Tasks currently waiting for human approval",
)

MEMORY_OPS = Counter(
    "agent_memory_ops_total",
    "Episodic memory operations",
    ["operation"],
)
