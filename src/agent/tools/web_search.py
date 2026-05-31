from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from agent.core.exceptions import ToolError
from agent.core.telemetry import TOOL_CALLS, TOOL_LATENCY, get_logger
from agent.tools.base import BaseTool

logger = get_logger(__name__)

_BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


class WebSearchTool(BaseTool):
    """Search the web using the Brave Search API."""

    name = "web_search"
    description = (
        "Search the web for information. Use when you need up-to-date facts, "
        "recent papers, or any information not in your training data."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."},
            "max_results": {
                "type": "integer",
                "description": "Number of results to return (1-10).",
                "default": 5,
            },
        },
        "required": ["query"],
    }
    is_destructive = False

    def __init__(self, api_key: str, timeout: int = 15, max_results: int = 5) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._default_max_results = max_results

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(2),
        wait=wait_fixed(1),
        reraise=True,
    )
    async def execute(self, **kwargs: Any) -> str:
        query: str = kwargs["query"]
        max_results: int = min(int(kwargs.get("max_results", self._default_max_results)), 10)

        if not self._api_key or self._api_key.startswith("BSA...") or len(self._api_key) < 20:
            return f"[web_search disabled — set a valid BRAVE_API_KEY in .env] Query: {query}"

        with TOOL_LATENCY.labels(tool=self.name).time():
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(
                        _BRAVE_SEARCH_URL,
                        headers={
                            "Accept": "application/json",
                            "X-Subscription-Token": self._api_key,
                        },
                        params={"q": query, "count": max_results},
                    )
                    resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                TOOL_CALLS.labels(tool=self.name, outcome="error").inc()
                raise ToolError(self.name, f"HTTP {exc.response.status_code}") from exc
            except httpx.TimeoutException as exc:
                TOOL_CALLS.labels(tool=self.name, outcome="timeout").inc()
                raise ToolError(self.name, "request timed out") from exc

        results = resp.json().get("web", {}).get("results", [])
        TOOL_CALLS.labels(tool=self.name, outcome="success").inc()

        if not results:
            return f"No results found for: {query}"

        lines = []
        for i, r in enumerate(results[:max_results], 1):
            lines.append(f"{i}. {r.get('title', 'No title')}")
            lines.append(f"   URL: {r.get('url', '')}")
            lines.append(f"   {r.get('description', '')}")
        return "\n".join(lines)
