# Architecture

## Overview

The agent follows the [ReAct](https://arxiv.org/abs/2210.03629) (Reasoning + Acting) pattern: the LLM is forced to always call a tool — either a real tool or the synthetic `final_answer` tool to exit the loop.

```
POST /api/v1/tasks { goal }
        │
        ▼
  TaskTrace created (in-memory store)
  Tracer created (SSE fan-out)
  ReactLoop.run() launched as BackgroundTask
        │
        ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  ReactLoop._loop()  (up to AGENT_MAX_ITERATIONS rounds)     │
   │                                                             │
   │  1. EpisodicMemory.search(goal, top_k=3)                    │
   │       → top-3 most similar past observations                │
   │                                                             │
   │  2. PromptBuilder                                           │
   │       → system prompt (ReAct instructions + memory)         │
   │       → messages (goal + prior steps)                       │
   │                                                             │
   │  3. LLMClient.call()      [tool_choice="required"]          │
   │       → thought (text from message.content)                 │
   │       → action  (tool name + input dict)                    │
   │                                                             │
   │  4. if action.tool == "final_answer":                       │
   │       → WorkingMemory.set_final_answer()                    │
   │       → Tracer.record_final()  → EXIT                       │
   │                                                             │
   │  5. ApprovalGate.check()                                    │
   │       → if is_destructive: raise HumanApprovalRequired      │
   │         WorkingMemory.set_status("waiting_approval")        │
   │         await ApprovalGate.wait()  [blocks on asyncio.Event]│
   │         if rejected: set_failed() → EXIT                    │
   │                                                             │
   │  6. ToolRegistry.get(name).execute(**input)                 │
   │       → ToolError / KeyError / TypeError → obs string       │
   │                                                             │
   │  7. EpisodicMemory.store(observation)                       │
   │                                                             │
   │  8. WorkingMemory.append_step(AgentStep)                    │
   │     Tracer.record_step(step) → fan-out to SSE queues        │
   │                                                             │
   │  → MaxIterationsError → set_failed()                        │
   └─────────────────────────────────────────────────────────────┘
```

---

## Module responsibilities

### `core/`

- **`config.py`** — `Settings` (pydantic-settings v2). `get_settings()` is `@lru_cache` — a single instance for the process lifetime. Tests that mutate env vars must call `get_settings.cache_clear()`.
- **`schemas.py`** — All Pydantic models: `Action`, `AgentStep`, `TaskTrace`, `TaskSummary`, `StepEvent`, `ProblemDetail`.
- **`exceptions.py`** — Exception hierarchy rooted at `AgentError(recoverable: bool)`. Only `LLMError` with HTTP 429/529 and `ToolError` are recoverable (trigger retry or LLM self-correction).
- **`telemetry.py`** — `structlog` configuration, Prometheus counters/histograms (`TASK_CREATED`, `TASK_STATUS`, `REACT_ITERATIONS`, `LLM_LATENCY`, `TOOL_CALLS`, `TOOL_LATENCY`, `MEMORY_OPS`, `APPROVAL_PENDING`), `get_logger()`.

### `llm/`

- **`client.py`** — `LLMClient` wraps `openai.AsyncOpenAI` pointed at OpenRouter. Converts internal `input_schema` → OpenAI `parameters` format. Appends `final_answer` synthetic tool to every request. Retries 3× on recoverable `LLMError` with exponential backoff.
- **`prompt_builder.py`** — `build_system_prompt()` injects ReAct instructions and episodic memory snippets. `build_messages()` turns the goal + step history into a message list.

### `memory/`

- **`embedder.py`** — `Embedder` wraps `fastembed.TextEmbedding` (`BAAI/bge-small-en-v1.5`, 384 dims, ONNX). The model is loaded once via `@lru_cache` and run in a thread pool (`asyncio.to_thread`) to avoid blocking the event loop.
- **`episodic.py`** — `EpisodicMemory` stores observations as Qdrant points (cosine distance). `search()` uses `query_points()` (qdrant-client ≥ 1.12). Raises `MemoryError` on any Qdrant failure.
- **`working.py`** — `WorkingMemory` is the **single source of truth** for a running task. It holds the `TaskTrace` reference and owns all mutations (`append_step`, `set_final_answer`, `set_failed`, `set_status`).

### `tools/`

- **`base.py`** — `Tool` structural Protocol + `BaseTool` mixin + `ToolRegistry`. Adding a tool never modifies existing code.
- Each tool subclasses `BaseTool`, declares `name`, `description`, `input_schema` (JSON Schema), `is_destructive`, and implements `async execute(**kwargs) -> str`.
- Tool errors are **returned as observation strings** — the agent can self-correct and retry.

### `runner/`

- **`react_loop.py`** — `ReactLoop` orchestrates the loop. **Does not** own trace mutations; delegates to `WorkingMemory`.
- **`approval_gate.py`** — `ApprovalGate` uses per-task `asyncio.Event`. `check()` raises immediately (non-blocking); `wait()` blocks. One gate instance is shared across all concurrent tasks.
- **`tracer.py`** — `Tracer` fans out `StepEvent` objects to `asyncio.Queue` instances (one per SSE subscriber). `subscribe()` returns a new queue; `stream()` drains it. **Never mutates the trace.**

### `api/`

- **`main.py`** — `create_app()` wires all dependencies; `lifespan()` initialises Qdrant, Embedder, ToolRegistry, LLMClient, ReactLoop on startup and closes Qdrant on shutdown.
- **`middleware.py`** — `JWTAuthMiddleware` validates Bearer tokens. `CorrelationIdMiddleware` injects `X-Request-ID`. Rate limiting via `slowapi`.
- **`routers/tasks.py`** — `_task_store: dict[str, TaskTrace]` is a module-level in-memory dict (swap point for Redis/DB). Task execution is launched as a FastAPI `BackgroundTask`.
- **`routers/stream.py`** — SSE endpoint. Handles the "already completed" case by replaying the terminal event immediately, avoiding a forever-blocking queue.

---

## Key invariants

1. **`tool_choice="required"`** — the LLM always calls a tool; plain text responses are treated as errors.
2. **`final_answer` is not registered** in `ToolRegistry`. `ReactLoop` intercepts it before dispatch.
3. **`WorkingMemory` owns all mutations.** `Tracer` is read-only with respect to the trace.
4. **Tool errors become observations**, not exceptions. The loop never aborts due to a tool failure.
5. **`ApprovalGate.check()` never blocks** — it raises immediately so the caller can persist state before suspending.
6. **`get_settings()` is cached** — tests must clear the cache when mutating env vars.

---

## Data flow for a destructive tool call

```
ReactLoop._loop()
  │
  ├─ LLMClient.call() → action.tool = "file_io", action.is_destructive = True
  │
  ├─ ApprovalGate.check()
  │     raises HumanApprovalRequired
  │
  ├─ WorkingMemory.set_status("waiting_approval")
  │   Tracer.record_waiting_approval("file_io") → SSE clients notified
  │
  ├─ await ApprovalGate.wait(task_id)
  │     ← blocks on asyncio.Event ─────────────────────────────────────────┐
  │                                                                        │
  │   POST /api/v1/tasks/{id}/approve  {"approved": true}                  │
  │     ApprovalGate.resolve(task_id, approved=True)                       │
  │     asyncio.Event.set()  ──────────────────────────────────────────────┘
  │
  ├─ WorkingMemory.set_status("running")
  └─ ToolRegistry.get("file_io").execute(**input) → observation
```
