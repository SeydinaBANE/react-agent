# Deployment

## Docker Compose (recommended)

The stack includes the API, Qdrant (vector store), Prometheus, and Grafana.

```bash
cp .env.example .env   # configure your keys
make dev               # docker compose up -d
```

| Service | Port | Description |
|---------|------|-------------|
| API | `8000` | ReAct Agent REST + SSE |
| Qdrant | `6333` / `6334` | Vector store (HTTP / gRPC) |
| Prometheus | `9090` | Metrics scraper |
| Grafana | `3000` | Dashboard (admin / admin) |

### Development overrides

`docker-compose.override.yml` is loaded automatically by Docker Compose and activates hot-reload and bind-mounted source code for local development.

```bash
make dev   # uses docker-compose.yml + docker-compose.override.yml
make down  # stop all services
```

---

## Docker image

The `docker/api.Dockerfile` uses a 3-stage build:

1. **deps** — install Python dependencies into a virtual env (layer cached unless `uv.lock` changes)
2. **src** — copy application source (layer cached unless source changes)
3. **runtime** — non-root user (`agent:agent`), copies venv + src, exposes port 8000

```bash
docker build -f docker/api.Dockerfile -t react-agent:latest .
docker run -p 8000:8000 --env-file .env react-agent:latest
```

---

## Production hardening

### Required environment variables

```bash
OPENROUTER_API_KEY=sk-or-...              # your OpenRouter key
JWT_SECRET_KEY=$(openssl rand -hex 32)    # strong random secret
```

### Recommended settings

```bash
LOG_FORMAT=json                           # structured logs for log aggregators
LOG_LEVEL=INFO
AGENT_CODE_EXECUTOR_ENABLED=false         # disable if you don't need code execution
FILE_IO_ALLOWED_PATHS=/workspace          # restrict to a specific volume
API_RATE_LIMIT=30/minute                  # tighten rate limit for public endpoints
```

### JWT token issuance

The API validates tokens but does **not** issue them — bring your own auth service. For development, generate tokens with:

```python
from jose import jwt
token = jwt.encode(
    {"sub": "user-id", "exp": 1800},  # add expiry in production
    secret_key,
    algorithm="HS256"
)
```

### Qdrant persistence

Qdrant data is stored in a named Docker volume (`qdrant_data`). Back it up regularly or point Qdrant at a managed instance (Qdrant Cloud) for production.

```yaml
# In docker-compose.yml, Qdrant is already configured with a volume:
volumes:
  qdrant_data:
```

### Scaling

The current in-memory task store (`_task_store` dict in `tasks.py`) is **not** shared across processes. To run multiple API replicas:

1. Replace `_task_store` with a Redis or database backend (the comment in `tasks.py` marks the swap point).
2. Replace the `asyncio.Event`-based `ApprovalGate` with a distributed event mechanism (e.g., Redis pub/sub).
3. Use a load balancer that routes SSE stream requests to the same instance as the task (or move to a message-queue-based architecture).

---

## Observability

### Prometheus metrics

The `/metrics` endpoint (enabled by default) exposes:

| Metric | Type | Description |
|--------|------|-------------|
| `agent_tasks_created_total` | Counter | Tasks submitted |
| `agent_task_status_total{status}` | Counter | Tasks by final status |
| `agent_react_iterations` | Histogram | Iterations per task |
| `agent_llm_latency_seconds` | Histogram | LLM call latency |
| `agent_tool_calls_total{tool,outcome}` | Counter | Tool calls by name and outcome |
| `agent_tool_latency_seconds{tool}` | Histogram | Per-tool execution latency |
| `agent_memory_ops_total{operation}` | Counter | Qdrant store/search/delete ops |
| `agent_approval_pending` | Gauge | Tasks currently waiting for approval |

### Grafana

Default credentials: `admin` / `admin` at `http://localhost:3000`.

Prometheus is pre-configured as a data source. Import a dashboard or build panels using the metrics above.

### Structured logs

All logs are emitted via `structlog` in JSON format (production) or pretty-printed (dev). Every log event includes `X-Request-ID` (correlation ID) for tracing requests across services.

```json
{
  "event": "task_completed",
  "task_id": "3f8a1b2c-...",
  "answer": "The capital of France is Paris.",
  "request_id": "9d4e1f2a-...",
  "timestamp": "2025-01-15T10:30:45Z"
}
```

---

## Health checks

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Liveness — returns `{"status": "ok"}` if the process is up |
| `GET /ready` | Readiness — returns `{"status": "ready"}` once `ApprovalGate` is initialised |

Use `/health` for Docker/Kubernetes liveness probes and `/ready` for readiness probes.
