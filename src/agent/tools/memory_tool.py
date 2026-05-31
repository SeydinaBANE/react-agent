from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.core.telemetry import TOOL_CALLS, TOOL_LATENCY, get_logger
from agent.tools.base import BaseTool

if TYPE_CHECKING:
    from agent.memory.episodic import EpisodicMemory

logger = get_logger(__name__)


class MemorySearchTool(BaseTool):
    """Search past observations stored in episodic memory (Qdrant)."""

    name = "memory_search"
    description = (
        "Search your episodic memory for past observations relevant to a query. "
        "Use this to recall results from previous tasks or iterations."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language query to search past observations.",
            },
            "top_k": {
                "type": "integer",
                "description": "Number of results to return (1-10).",
                "default": 5,
            },
        },
        "required": ["query"],
    }
    is_destructive = False

    def __init__(self, memory: EpisodicMemory) -> None:
        self._memory = memory

    async def execute(self, **kwargs: Any) -> str:
        query: str = kwargs["query"]
        top_k: int = min(int(kwargs.get("top_k", 5)), 10)

        with TOOL_LATENCY.labels(tool=self.name).time():
            results = await self._memory.search(query, top_k=top_k)

        TOOL_CALLS.labels(tool=self.name, outcome="success").inc()

        if not results:
            return f"No relevant memories found for: {query}"

        lines = [f"Found {len(results)} relevant past observation(s):"]
        for i, obs in enumerate(results, 1):
            lines.append(f"\n--- Memory {i} ---\n{obs}")
        return "\n".join(lines)
