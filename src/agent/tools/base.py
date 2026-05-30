from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from agent.core.exceptions import ToolNotFoundError


@runtime_checkable
class Tool(Protocol):
    """Structural interface that every tool must satisfy."""

    name: str
    description: str
    input_schema: dict[str, Any]
    is_destructive: bool

    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool and return the observation as a string."""
        ...  # pragma: no cover

    def to_anthropic_schema(self) -> dict[str, Any]:
        """Return the Claude tool_use JSON Schema for this tool."""
        ...  # pragma: no cover


class BaseTool:
    """Mixin providing `to_anthropic_schema` for concrete tool classes."""

    name: str
    description: str
    input_schema: dict[str, Any]
    is_destructive: bool = False

    def to_anthropic_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolRegistry:
    """Central registry for all available tools."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise ToolNotFoundError(name)
        return self._tools[name]

    def all_schemas(self) -> list[dict[str, Any]]:
        return [t.to_anthropic_schema() for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools.keys())
