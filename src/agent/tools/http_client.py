from __future__ import annotations

import json as _json
from typing import Any

import httpx

from agent.core.exceptions import ToolError
from agent.core.telemetry import TOOL_CALLS, TOOL_LATENCY, get_logger
from agent.tools.base import BaseTool

logger = get_logger(__name__)


class HttpClientTool(BaseTool):
    """Make HTTP GET or POST requests to arbitrary URLs."""

    name = "http_client"
    description = (
        "Make HTTP requests (GET or POST) to any URL and return the response body. "
        "Use for calling REST APIs, fetching web pages, or retrieving structured data."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "method": {
                "type": "string",
                "enum": ["GET", "POST"],
                "description": "HTTP method.",
                "default": "GET",
            },
            "url": {"type": "string", "description": "Full URL to request."},
            "headers": {
                "type": "object",
                "description": "Optional HTTP headers as key-value pairs.",
            },
            "body": {
                "type": "object",
                "description": "Optional JSON body for POST requests.",
            },
        },
        "required": ["url"],
    }
    is_destructive = False

    def __init__(
        self,
        timeout: int = 15,
        max_response_chars: int = 10_000,
        allowed_url_prefixes: list[str] | None = None,
    ) -> None:
        self._timeout = timeout
        self._max_chars = max_response_chars
        self._allowed_prefixes = allowed_url_prefixes or []

    def _check_url(self, url: str) -> None:
        if not self._allowed_prefixes:
            return
        if not any(url.startswith(prefix) for prefix in self._allowed_prefixes):
            raise ToolError(self.name, f"URL '{url}' is not in the allowed list.")

    async def execute(self, **kwargs: Any) -> str:
        url: str = kwargs["url"]
        method: str = kwargs.get("method", "GET").upper()
        headers: dict[str, str] = kwargs.get("headers", {})
        body: dict[str, Any] | None = kwargs.get("body")

        self._check_url(url)

        with TOOL_LATENCY.labels(tool=self.name).time():
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    if method == "GET":
                        resp = await client.get(url, headers=headers)
                    else:
                        resp = await client.post(url, headers=headers, json=body)
                    resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                TOOL_CALLS.labels(tool=self.name, outcome="error").inc()
                raise ToolError(self.name, f"HTTP {exc.response.status_code}: {url}") from exc
            except httpx.TimeoutException as exc:
                TOOL_CALLS.labels(tool=self.name, outcome="timeout").inc()
                raise ToolError(self.name, f"Timeout requesting {url}") from exc

        TOOL_CALLS.labels(tool=self.name, outcome="success").inc()
        text = resp.text[: self._max_chars]
        return f"[{method} {url}] Status {resp.status_code}\n{text}"
