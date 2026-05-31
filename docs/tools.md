# Tools

The agent ships with 5 built-in tools. Each tool is a `BaseTool` subclass registered at startup.

---

## web_search

Search the web using the [Brave Search API](https://brave.com/search/api/).

**Enabled when:** `BRAVE_API_KEY` is set to a valid key (≥ 20 chars, not a placeholder).
**Silently disabled when:** `BRAVE_API_KEY` is empty or a placeholder — the agent falls back to other tools.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | The search query |
| `max_results` | integer | No | Number of results (1–10, default 5) |

**Returns:** Numbered list of `title`, `url`, and `description` for each result.

**Limits:** Retries once on network error; 15-second timeout.

---

## code_executor

Execute Python code in a sandboxed subprocess with a hard timeout.

**Disabled when:** `AGENT_CODE_EXECUTOR_ENABLED=false`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `code` | string | Yes | Python code to execute |

**Returns:** Combined stdout + stderr (truncated to 5 000 chars). Returns `(no output)` if empty.

**Sandbox restrictions:**
- Forbidden imports: `os`, `subprocess`, `sys`, `socket`, `importlib`, `shutil`, `signal`, `ctypes`
- No network access
- No file system access (use `file_io` instead)
- Killed after `AGENT_TOOL_TIMEOUT` seconds (default 10)

```python
# Example input
{
  "code": "import math\nresult = math.sqrt(144)\nprint(f'Square root: {result}')"
}
# Output: "Square root: 12.0\n"
```

---

## file_io

Read and write files within a configurable path whitelist.

**`is_destructive = True` for write/delete operations** — those calls pause for human approval.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | Yes | `read`, `write`, or `delete` |
| `path` | string | Yes | Absolute path within allowed paths |
| `content` | string | Conditional | Required for `write` |

**Allowed paths:** Configured via `FILE_IO_ALLOWED_PATHS` (default `/tmp,/workspace`). Any path outside this whitelist is rejected.

**Max file size:** 1 MB for reads.

---

## http_client

Make HTTP requests to external APIs.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | Yes | Target URL |
| `method` | string | No | `GET`, `POST`, `PUT`, `DELETE` (default `GET`) |
| `headers` | object | No | Request headers |
| `body` | string | No | Request body |

**Returns:** Response body (truncated to 10 000 chars) with status code prefix.

**Limits:** 15-second timeout. No URL restrictions by default (configurable via `config/tools.yaml`).

---

## memory_search

Semantic search over past observations stored in Qdrant.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Natural language search query |
| `top_k` | integer | No | Number of results (default 5) |

**Returns:** The `top_k` most semantically similar past observations, ordered by cosine similarity.

**Score threshold:** 0.6 (results below this score are filtered out).

---

## Adding a new tool

1. **Create the tool file** — `src/agent/tools/my_tool.py`:

```python
from __future__ import annotations
from typing import Any
from agent.core.exceptions import ToolError
from agent.tools.base import BaseTool

class MyTool(BaseTool):
    name = "my_tool"
    description = "Clear description — when and why to use this tool."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "param": {"type": "string", "description": "What this param does."},
        },
        "required": ["param"],
    }
    is_destructive = False  # set True if the tool writes/deletes external state

    async def execute(self, **kwargs: Any) -> str:
        param: str = kwargs["param"]
        try:
            result = await _do_something(param)
            return result
        except SomeError as exc:
            raise ToolError(self.name, str(exc)) from exc
```

2. **Register at startup** — in `src/agent/api/main.py`, inside `lifespan()`:

```python
registry.register(MyTool())
```

3. **Write a unit test** — in `tests/unit/test_tools.py`:

```python
async def test_my_tool_success():
    tool = MyTool()
    result = await tool.execute(param="test input")
    assert "expected" in result

async def test_my_tool_error():
    tool = MyTool()
    with pytest.raises(ToolError):
        await tool.execute(param="bad input that causes error")
```

4. **Document in `config/tools.yaml`**:

```yaml
tools:
  my_tool:
    timeout_seconds: 10
    # add any tool-specific config here
```

### Design rules for tools

- Always return a **descriptive string** — the LLM reads it as an observation.
- Raise `ToolError(self.name, message)` on expected failures; let unexpected exceptions bubble (they'll be caught by `ReactLoop._execute_tool()` and converted to observations).
- Set `is_destructive = True` for any write/delete/send operation — this triggers the human approval gate.
- Keep `execute()` idempotent where possible.
- Use `asyncio.to_thread()` for blocking I/O inside `execute()`.
