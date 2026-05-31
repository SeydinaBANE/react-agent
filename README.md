# ReAct Agent

**Autonomous LLM agent** built on the [ReAct](https://arxiv.org/abs/2210.03629) pattern — the agent thinks, picks a tool, observes the result, and repeats until it has a final answer.

[![CI](https://github.com/SeydinaBANE/react-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/SeydinaBANE/react-agent/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

---

## Features

- **ReAct loop** — structured Thought → Action → Observation iterations with a configurable max (default 15)
- **5 built-in tools** — web search (Brave), Python code execution, file I/O, HTTP client, episodic memory search
- **Episodic memory** — every observation is embedded (`BAAI/bge-small-en-v1.5`, ONNX, 384 dims) and stored in Qdrant; top-3 relevant memories are injected into each prompt
- **Human-in-the-loop approval** — destructive tool calls suspend the task until a human approves via the API
- **Live streaming** — Server-Sent Events stream each iteration step in real time
- **Production-ready API** — FastAPI + JWT auth + rate limiting + RFC 7807 errors + Prometheus metrics
- **OpenRouter routing** — any model available on OpenRouter (Claude, GPT-4o, Gemini…)

---

## Architecture

```
POST /api/v1/tasks { goal }
        │
        ▼
   ReactLoop (max N iterations)
  ┌────────────────────────────────────────────────┐
  │  1. EpisodicMemory  →  recall top-3 memories   │
  │  2. PromptBuilder   →  system + history        │
  │  3. LLMClient       →  thought + tool call     │
  │  4. ApprovalGate    →  suspend if destructive  │
  │  5. ToolRegistry    →  execute tool            │
  │  6. EpisodicMemory  →  store observation       │
  │  7. Tracer          →  fan-out SSE events      │
  └────────────────────────────────────────────────┘
        │
        ▼
  GET /api/v1/tasks/{id}/trace   →  full JSON trace
  GET /api/v1/tasks/{id}/stream  →  SSE live steps
```

See [docs/architecture.md](docs/architecture.md) for a deeper dive.

---

## Quick Start

### With Docker (recommended)

```bash
git clone https://github.com/SeydinaBANE/react-agent.git
cd react-agent
cp .env.example .env       # fill in OPENROUTER_API_KEY and JWT_SECRET_KEY
make dev                   # starts API + Qdrant + Prometheus + Grafana
```

The API is now available at `http://localhost:8000`. Docs at `http://localhost:8000/docs`.

### Submit your first task

```bash
# Auto-generates a dev JWT from JWT_SECRET_KEY in .env
make run GOAL="What are the 3 most cited ML papers from 2024?"
```

Or with `curl`:

```bash
TOKEN=$(python -c "
from jose import jwt; import os
print(jwt.encode({'sub':'dev'}, os.environ['JWT_SECRET_KEY'], algorithm='HS256'))
")

# Submit
TASK=$(curl -s -X POST http://localhost:8000/api/v1/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"goal": "Summarize the ReAct paper in 3 bullet points"}')

echo $TASK | python -m json.tool
TASK_ID=$(echo $TASK | python -c "import sys,json; print(json.load(sys.stdin)['task_id'])")

# Stream results live
curl -N http://localhost:8000/api/v1/tasks/$TASK_ID/stream \
  -H "Authorization: Bearer $TOKEN"

# Or fetch the full trace when done
curl http://localhost:8000/api/v1/tasks/$TASK_ID/trace \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

### Local development (no Docker)

```bash
make install    # uv sync --all-extras + pre-commit install
make server     # uvicorn with hot-reload (needs Qdrant running separately)
```

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/tasks` | Submit a goal → returns `task_id` (202) |
| `GET` | `/api/v1/tasks/{id}` | Task summary (status, iterations) |
| `GET` | `/api/v1/tasks/{id}/trace` | Full trace with all steps |
| `GET` | `/api/v1/tasks/{id}/stream` | SSE stream of live steps |
| `POST` | `/api/v1/tasks/{id}/approve` | Approve or reject a destructive action |
| `GET` | `/health` | Liveness probe |
| `GET` | `/ready` | Readiness probe |
| `GET` | `/metrics` | Prometheus metrics |
| `GET` | `/docs` | Interactive Swagger UI |

See [docs/api.md](docs/api.md) for full request/response schemas and examples.

---

## Tools

| Tool | Description | Destructive |
|------|-------------|-------------|
| `web_search` | Brave Search API — up to 10 results | No |
| `code_executor` | Run Python in a sandboxed subprocess | No |
| `file_io` | Read/write files within allowed paths | Write: Yes |
| `http_client` | Make arbitrary HTTP requests | No |
| `memory_search` | Semantic search over past observations | No |

`web_search` is silently disabled when `BRAVE_API_KEY` is not set — the agent falls back to other tools.

See [docs/tools.md](docs/tools.md) for parameters, limits, and how to add a new tool.

---

## Configuration

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENROUTER_API_KEY` | ✅ | — | OpenRouter API key (`sk-or-…`) |
| `JWT_SECRET_KEY` | ✅ | — | HS256 secret, min 32 characters |
| `AGENT_MODEL` | | `anthropic/claude-haiku-4.5` | Any OpenRouter model string |
| `BRAVE_API_KEY` | | *(disabled)* | Enables `web_search` tool |
| `AGENT_MAX_ITERATIONS` | | `15` | Max ReAct iterations (≤ 50) |
| `AGENT_TOOL_TIMEOUT` | | `10` | Per-tool timeout in seconds |
| `QDRANT_HOST` | | `localhost` | Qdrant host |
| `FILE_IO_ALLOWED_PATHS` | | `/tmp,/workspace` | Comma-separated path whitelist |
| `LOG_FORMAT` | | `json` | `json` (prod) or `pretty` (dev) |
| `PROMETHEUS_ENABLED` | | `true` | Expose `/metrics` endpoint |

---

## Development

```bash
make all-checks   # lint + typecheck + unit tests + security scan (mirrors CI)
make lint         # ruff check (read-only)
make format       # ruff fix + format
make typecheck    # mypy strict
make test-unit    # fast unit tests, no external services
make test-int     # integration tests (requires Docker)
```

Run a single test:

```bash
uv run pytest tests/unit/test_tools.py::TestWebSearchTool::test_disabled_when_no_key -v
```

### Adding a new tool

1. Create `src/agent/tools/my_tool.py` — subclass `BaseTool`, implement `execute(**kwargs) -> str`
2. Register it in `src/agent/api/main.py` → `registry.register(MyTool())` inside `lifespan`
3. Add a unit test in `tests/unit/test_tools.py`
4. Document it in `config/tools.yaml`

See [docs/tools.md](docs/tools.md) for a full walkthrough.

---

## Deployment

See [docs/deployment.md](docs/deployment.md) for production Docker setup, environment hardening, and observability (Prometheus + Grafana).

---

## License

MIT — see [LICENSE](LICENSE).
