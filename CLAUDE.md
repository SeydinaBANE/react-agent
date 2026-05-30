# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Autonomous LLM agent following the **ReAct** pattern (Reasoning + Acting). Given a goal, the agent iterates: think → choose a tool → execute it → observe the result → repeat until a final answer is produced or max iterations are reached.

---

## Commands

```bash
make install        # uv sync --all-extras + pre-commit install
make dev            # docker compose up -d (API + Qdrant + Prometheus + Grafana)
make down           # stop all services
make server         # run API locally with hot-reload (no Docker)
make all-checks     # lint + typecheck + test-unit + security (CI equivalent)

make lint           # ruff check + format --check (read-only)
make format         # ruff check --fix + ruff format (auto-fix)
make typecheck      # mypy strict

make test-unit      # unit tests only, fast, no external services
make test-int       # integration tests (requires running Docker services)
make test-all       # unit + integration

make run GOAL="..."  # submit a task via CLI
make trace ID="..."  # inspect a completed task trace
make schema         # export OpenAPI JSON to openapi.json
make bump           # commitizen version bump + CHANGELOG update
```

**Run a single test:**
```bash
uv run pytest tests/unit/test_tools.py -v                         # whole file
uv run pytest tests/unit/test_tools.py::TestName::test_method -v  # one test
```

---

## Environment variables

Copy `.env.example` to `.env`. Required keys:
- `OPENROUTER_API_KEY` — routes LLM calls through OpenRouter (OpenAI-compatible endpoint)
- `JWT_SECRET_KEY` — API authentication secret (min 32 chars)

Optional:
- `BRAVE_API_KEY` — enables `web_search` tool (empty string disables it gracefully)
- `AGENT_MODEL` — default `anthropic/claude-3.5-sonnet` (OpenRouter model string)
- `AGENT_CODE_EXECUTOR_ENABLED` — set `false` to disable sandboxed code execution

`get_settings()` is `@lru_cache`. Tests that mutate env vars must call `get_settings.cache_clear()` in teardown.

---

## Architecture

```
POST /api/v1/tasks { goal }
        │
        ▼
   ReactLoop (runner/react_loop.py)
  ┌──────────────────────────────────────────────────────────┐
  │  For each iteration (max = AGENT_MAX_ITERATIONS):        │
  │                                                          │
  │  1. PromptBuilder  ──→  system prompt + history + memory │
  │  2. LLMClient      ──→  OpenRouter tool_use response     │
  │     ├─ thought (reasoning text)                          │
  │     └─ action (tool name + input dict)                   │
  │  3. ApprovalGate   ──→  suspend if action.is_destructive │
  │  4. ToolRegistry   ──→  execute selected tool            │
  │  5. EpisodicMemory ──→  embed + store observation        │
  │  6. Tracer         ──→  append AgentStep to trace        │
  │  7. Check FINAL_ANSWER stop signal                       │
  └──────────────────────────────────────────────────────────┘
        │
        ▼
  GET /api/v1/tasks/{id}/trace  ──→  TaskTrace JSON
  GET /api/v1/tasks/{id}/stream ──→  SSE live steps
```

---

## Key design decisions

**LLM via OpenRouter** — `LLMClient` wraps `openai.AsyncOpenAI` pointed at `openrouter.ai/api/v1`. Model names use OpenRouter's format (`anthropic/claude-3.5-sonnet`). Tool schemas are converted from the internal `input_schema` field to OpenAI's `parameters` field in `_to_openai_tool()`.

**Protocol Tool** (`tools/base.py`) — each tool is a structural subtype of `Tool`. Adding a new tool never touches existing code (open/closed). The `input_schema` field is the JSON Schema used for tool routing.

**Deterministic tool routing** — the model selects tools by name via tool_use/function-calling; no regex parsing of LLM output, no prompt injection risk.

**Tool errors as observations** — `ToolError` exceptions are caught in `_execute_tool()` and returned as an observation string so the LLM can recover, rather than aborting the loop.

**ApprovalGate** — any tool with `is_destructive=True` suspends the task (status → `waiting_approval`). The task resumes only after `POST /api/v1/tasks/{id}/approve`. This makes write/delete operations safe in production.

**Episodic memory (Qdrant)** — each observation is embedded (`sentence-transformers`) and stored. At each iteration, the top-3 most similar past observations are injected into the prompt context.

**Correlation IDs** — every request gets a UUID injected via `CorrelationIdMiddleware`. Propagated through all structlog events and returned as `X-Request-ID` response header.

**RFC 7807 error responses** — all HTTP errors return `ProblemDetail` (`{"type", "title", "status", "detail", "instance"}`). Never plain strings.

---

## Adding a new tool

1. Create `src/agent/tools/my_tool.py`, subclass `BaseTool`:
   ```python
   class MyTool(BaseTool):
       name = "my_tool"
       description = "What it does, when to use it."
       input_schema = {"type": "object", "properties": {...}, "required": [...]}
       is_destructive = False  # set True if it writes/deletes

       async def execute(self, **kwargs: Any) -> str:
           ...
           return result_str
   ```
2. Register in `src/agent/api/main.py` → `registry.register(MyTool())` inside `lifespan`.
3. Add a unit test in `tests/unit/test_tools.py` (mock external calls with `pytest-httpx` or `AsyncMock`).
4. Document in `config/tools.yaml` (timeout, rate limit, whitelist if applicable).

---

## Testing strategy

- **Unit tests** (`tests/unit/`) — LLM responses mocked via `pytest-httpx` / `AsyncMock`. No external services needed. Fast (~seconds).
- **Integration tests** (`tests/integration/`) — Qdrant via Testcontainers. Requires Docker.
- **Coverage threshold** — `--cov-fail-under=80` enforced in CI.
- `asyncio_mode = "auto"` in pytest config — no `@pytest.mark.asyncio` decorator needed on async tests.

---

## Module map

```
src/agent/
├── core/        config (Settings/get_settings), schemas, exceptions, telemetry
├── llm/         OpenRouter client (openai SDK), prompt builder
├── memory/      episodic (Qdrant), working state (WorkingMemory), embedder
├── tools/       base protocol + registry, 5 tools: web_search, code_executor,
│                file_io, http_client, memory_search
├── runner/      ReactLoop, ApprovalGate, Tracer
└── api/         FastAPI app + lifespan wiring, middleware, task/stream routers
```
