from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from qdrant_client import AsyncQdrantClient
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.responses import Response

from agent.api.middleware import (
    CorrelationIdMiddleware,
    JWTAuthMiddleware,
    rate_limit_handler,
)
from agent.api.routers import stream, tasks
from agent.core.config import get_settings
from agent.core.schemas import ProblemDetail
from agent.core.telemetry import configure_logging, get_logger
from agent.llm.client import LLMClient
from agent.memory.embedder import Embedder
from agent.memory.episodic import EpisodicMemory
from agent.runner.approval_gate import ApprovalGate
from agent.runner.react_loop import ReactLoop
from agent.tools.base import ToolRegistry
from agent.tools.code_executor import CodeExecutorTool
from agent.tools.file_io import FileIOTool
from agent.tools.http_client import HttpClientTool
from agent.tools.memory_tool import MemorySearchTool
from agent.tools.web_search import WebSearchTool

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    # ── Dependencies ─────────────────────────────────────────────────────────
    embedder = Embedder()
    qdrant = AsyncQdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
    memory = EpisodicMemory(qdrant, embedder, settings.qdrant_collection)
    await memory.ensure_collection()

    gate = ApprovalGate()

    registry = ToolRegistry()
    registry.register(WebSearchTool(api_key=settings.brave_api_key))
    registry.register(
        CodeExecutorTool(
            timeout_s=settings.agent_tool_timeout,
            enabled=settings.agent_code_executor_enabled,
        )
    )
    registry.register(FileIOTool(allowed_paths=settings.file_io_allowed_paths_list))
    registry.register(HttpClientTool())

    registry.register(MemorySearchTool(memory=memory))

    llm = LLMClient(
        api_key=settings.openrouter_api_key,
        model=settings.agent_model,
        base_url=settings.openrouter_base_url,
    )
    react_loop = ReactLoop(
        llm=llm,
        registry=registry,
        memory=memory,
        gate=gate,
        max_iterations=settings.agent_max_iterations,
    )

    # ── Attach to app.state ──────────────────────────────────────────────────
    app.state.react_loop = react_loop
    app.state.approval_gate = gate
    app.state.tracer_registry = {}

    logger.info("agent_startup_complete", model=settings.agent_model)
    yield

    # ── Graceful shutdown ────────────────────────────────────────────────────
    await qdrant.close()
    logger.info("agent_shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    limiter = Limiter(key_func=get_remote_address, default_limits=[settings.api_rate_limit])

    app = FastAPI(
        title="ReAct Agent API",
        version="0.1.0",
        description="Autonomous ReAct agent with episodic memory and tool use.",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.state.limiter = limiter
    app.add_exception_handler(Exception, _global_error_handler)
    from slowapi.errors import RateLimitExceeded

    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

    # ── Middleware (LIFO order: last added = outermost) ───────────────────────
    app.add_middleware(
        JWTAuthMiddleware,
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    app.add_middleware(CorrelationIdMiddleware)

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(tasks.router)
    app.include_router(stream.router)

    # ── Utility endpoints ─────────────────────────────────────────────────────
    @app.get("/health", tags=["ops"], include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["ops"], include_in_schema=False)
    async def ready(request: Request) -> dict[str, str]:
        try:
            return {"status": "ready"}
        except AttributeError:
            return JSONResponse(status_code=503, content={"status": "not ready"})  # type: ignore[return-value]

    if settings.prometheus_enabled:

        @app.get("/metrics", tags=["ops"], include_in_schema=False)
        async def metrics() -> Response:
            return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


async def _global_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_error", path=str(request.url))
    body = ProblemDetail(
        title="Internal Server Error",
        status=500,
        detail="An unexpected error occurred.",
        instance=str(request.url),
    )
    return JSONResponse(
        status_code=500,
        content=body.model_dump(),
        media_type="application/problem+json",
    )


app = create_app()
