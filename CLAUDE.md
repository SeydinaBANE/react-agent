# ReAct Agent — Architecture Guide

## Purpose

Autonomous LLM agent following the **ReAct** pattern (Reasoning + Acting). Given a goal, the agent iterates: think → choose a tool → execute it → observe the result → repeat until a final answer is produced or max iterations are reached.

Use cases: research tasks, multi-step data gathering, code generation + execution, document synthesis.

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
  │  2. LLMClient      ──→  Claude tool_use response         │
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

**Protocol Tool** (`tools/base.py`) — each tool is a structural subtype of `Tool`. Adding a new tool never touches existing code (open/closed). The `input_schema` field is the JSON Schema fed directly to Claude's tool_use API.

**Deterministic tool routing** — Claude selects tools by name via tool_use; no regex parsing of LLM output, no prompt injection risk.

**ApprovalGate** — any tool with `is_destructive=True` suspends the task (status → `waiting_approval`). The task resumes only after `POST /api/v1/tasks/{id}/approve`. This makes write/delete operations safe in production.

**Episodic memory (Qdrant)** — each observation is embedded and stored. At each iteration, the top-k most similar past observations are injected into the prompt context, giving the agent long-term memory across tasks.

**Correlation IDs** — every request gets a UUID injected via middleware. Propagated through all structlog events and returned as `X-Request-ID` response header. Essential for distributed tracing.

**RFC 7807 error responses** — all HTTP errors return `{"type", "title", "status", "detail", "instance"}`. Never plain strings.

---

## Adding a new tool

1. Create `src/agent/tools/my_tool.py`, implement the `Tool` protocol:
   ```python
   class MyTool:
       name = "my_tool"
       description = "What it does, when to use it."
       input_schema = {"type": "object", "properties": {...}, "required": [...]}
       is_destructive = False  # set True if it writes/deletes

       async def execute(self, **kwargs: Any) -> str:
           ...
           return result_str
   ```
2. Register in `src/agent/tools/base.py` → `ToolRegistry.register(MyTool())`.
3. Add a unit test in `tests/unit/test_tools.py` (mock external calls with `pytest-httpx` or `unittest.mock`).
4. Document in `config/tools.yaml` (timeout, rate limit, whitelist if applicable).

---

## Development workflow

```bash
make install        # uv sync + pre-commit install
make dev            # docker compose up (Qdrant + Prometheus + Grafana)
make server         # run API locally with hot-reload
make all-checks     # lint + mypy + tests + security (CI equivalent)
make run GOAL="..."  # submit a task via CLI
make trace ID="..."  # inspect a completed task trace
```

---

## Environment variables

See `.env.example` for the full list with descriptions. Required keys:
- `ANTHROPIC_API_KEY` — Anthropic API key
- `JWT_SECRET_KEY` — API authentication secret (min 32 chars in production)

---

## Testing strategy

- **Unit tests** (`tests/unit/`) — LLM responses mocked via `pytest-httpx` / `AsyncMock`. No external services needed. Fast (~seconds).
- **Integration tests** (`tests/integration/`) — Qdrant via Testcontainers. Requires Docker.
- **Coverage threshold** — `--cov-fail-under=80` enforced in both `make test-unit` and CI.
- Run `make test-unit` before every commit (pre-commit runs it on push via CI).

---

## Module map

```
src/agent/
├── core/        config, schemas, exceptions, telemetry
├── llm/         Anthropic client, prompt builder
├── memory/      episodic (Qdrant), working state, embedder
├── tools/       base protocol, registry, 5 tool implementations
├── runner/      ReAct loop, approval gate, trace exporter
└── api/         FastAPI app, middleware, routers
```
