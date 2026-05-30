from __future__ import annotations


class AgentError(Exception):
    """Base exception for all agent errors."""

    def __init__(self, message: str, *, recoverable: bool = False) -> None:
        super().__init__(message)
        self.recoverable = recoverable


class MaxIterationsError(AgentError):
    """Raised when the agent exceeds max_iterations without a final answer."""


class ToolError(AgentError):
    """Raised when a tool execution fails."""

    def __init__(self, tool_name: str, message: str) -> None:
        super().__init__(f"[{tool_name}] {message}", recoverable=True)
        self.tool_name = tool_name


class ToolNotFoundError(AgentError):
    """Raised when the LLM requests a tool that is not registered."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"Tool '{tool_name}' is not registered.")
        self.tool_name = tool_name


class ToolTimeoutError(ToolError):
    """Raised when a tool execution exceeds the configured timeout."""

    def __init__(self, tool_name: str, timeout_s: int) -> None:
        super().__init__(tool_name, f"timed out after {timeout_s}s")
        self.timeout_s = timeout_s


class HumanApprovalRequired(AgentError):
    """Raised when a destructive action requires human approval before proceeding."""

    def __init__(self, task_id: str, tool_name: str) -> None:
        super().__init__(
            f"Task {task_id}: tool '{tool_name}' requires human approval.",
            recoverable=True,
        )
        self.task_id = task_id
        self.tool_name = tool_name


class MemoryError(AgentError):
    """Raised on episodic memory (Qdrant) failures."""


class LLMError(AgentError):
    """Raised when the Anthropic API call fails."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message, recoverable=status_code in {429, 529})
        self.status_code = status_code


class ConfigurationError(AgentError):
    """Raised on invalid / missing configuration at startup."""
