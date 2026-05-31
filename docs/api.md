# API Reference

Base URL: `http://localhost:8000`

All `/api/v1/` routes require a `Bearer` JWT token in the `Authorization` header.
Exempt routes: `/health`, `/ready`, `/metrics`, `/docs`, `/redoc`, `/openapi.json`.

---

## Authentication

The API uses HS256 JWT tokens. Generate a dev token from your `JWT_SECRET_KEY`:

```python
from jose import jwt
token = jwt.encode({"sub": "dev"}, "your-jwt-secret", algorithm="HS256")
```

Or use the CLI shortcut:
```bash
make run GOAL="..."   # auto-generates token from .env
```

---

## Endpoints

### POST /api/v1/tasks

Submit a goal to the agent. Returns immediately (HTTP 202); execution runs in the background.

**Request**
```json
{
  "goal": "Research and summarize the top 3 ML papers from 2024"
}
```
- `goal` — string, 1–2000 characters, required

**Response** `202 Accepted`
```json
{
  "task_id": "3f8a1b2c-...",
  "goal": "Research and summarize the top 3 ML papers from 2024",
  "status": "running",
  "iterations": 0,
  "created_at": "2025-01-15T10:30:00Z",
  "completed_at": null
}
```

**Example**
```bash
curl -X POST http://localhost:8000/api/v1/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"goal": "What is the capital of France?"}'
```

---

### GET /api/v1/tasks/{task_id}

Get the current status and summary of a task.

**Response** `200 OK`
```json
{
  "task_id": "3f8a1b2c-...",
  "goal": "...",
  "status": "completed",
  "iterations": 4,
  "created_at": "2025-01-15T10:30:00Z",
  "completed_at": "2025-01-15T10:30:45Z"
}
```

**Status values**

| Status | Meaning |
|--------|---------|
| `running` | Agent is actively iterating |
| `waiting_approval` | A destructive tool call needs human approval |
| `completed` | Agent produced a final answer |
| `failed` | Max iterations reached or unrecoverable error |

---

### GET /api/v1/tasks/{task_id}/trace

Full trace of all agent steps.

**Response** `200 OK`
```json
{
  "task_id": "3f8a1b2c-...",
  "goal": "What is the capital of France?",
  "status": "completed",
  "final_answer": "The capital of France is Paris.",
  "steps": [
    {
      "iteration": 1,
      "thought": "I can answer this directly.",
      "action": {
        "tool": "final_answer",
        "input": {"answer": "The capital of France is Paris."},
        "is_destructive": false
      },
      "observation": "",
      "latency_ms": 312,
      "timestamp": "2025-01-15T10:30:01Z"
    }
  ],
  "created_at": "2025-01-15T10:30:00Z",
  "completed_at": "2025-01-15T10:30:01Z"
}
```

```bash
make trace ID="3f8a1b2c-..."
# or
curl http://localhost:8000/api/v1/tasks/3f8a1b2c-.../trace \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

---

### GET /api/v1/tasks/{task_id}/stream

Stream agent steps as [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events) until the task completes.

**Media type:** `text/event-stream`

**Event types**

| Event | Data | Description |
|-------|------|-------------|
| `step` | `AgentStep` JSON | One completed ReAct iteration |
| `final` | answer string | Task completed successfully |
| `error` | error string | Task failed |
| `waiting_approval` | tool name | Destructive action needs approval |

**Example (curl)**
```bash
curl -N http://localhost:8000/api/v1/tasks/3f8a1b2c-.../stream \
  -H "Authorization: Bearer $TOKEN"
```

**Example (JavaScript)**
```js
const es = new EventSource(`/api/v1/tasks/${taskId}/stream`, {
  headers: { Authorization: `Bearer ${token}` }
});

es.addEventListener('step', e => {
  const step = JSON.parse(e.data);
  console.log(`[${step.data.iteration}] ${step.data.action.tool}`);
});

es.addEventListener('final', e => {
  console.log('Answer:', JSON.parse(e.data).data);
  es.close();
});
```

If the task is already completed when you connect, the terminal event is replayed immediately.

---

### POST /api/v1/tasks/{task_id}/approve

Approve or reject a pending destructive action (when task status is `waiting_approval`).

**Request**
```json
{
  "approved": true,
  "reason": "Reviewed and looks safe"
}
```

**Response** `200 OK`
```json
{
  "approved": true,
  "task_id": "3f8a1b2c-..."
}
```

Returns `409 Conflict` if the task is not waiting for approval.

```bash
curl -X POST http://localhost:8000/api/v1/tasks/3f8a1b2c-.../approve \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"approved": true, "reason": "looks good"}'
```

---

## Error format

All errors follow [RFC 7807](https://datatracker.ietf.org/doc/html/rfc7807):

```json
{
  "type": "about:blank",
  "title": "Not Found",
  "status": 404,
  "detail": "Task '3f8a1b2c-...' not found.",
  "instance": "/api/v1/tasks/3f8a1b2c-.../trace"
}
```

**Content-Type:** `application/problem+json`

---

## Rate limiting

Default: 60 requests per minute per IP (configurable via `API_RATE_LIMIT`).

Exceeding the limit returns `429 Too Many Requests`.

---

## OpenAPI / Swagger

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- JSON schema: `http://localhost:8000/openapi.json`

Export schema locally:
```bash
make schema   # writes openapi.json
```
