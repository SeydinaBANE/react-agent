from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from agent.core.exceptions import ToolError
from agent.core.telemetry import TOOL_CALLS, TOOL_LATENCY, get_logger
from agent.tools.base import BaseTool

logger = get_logger(__name__)

_MAX_FILE_SIZE = 1024 * 1024  # 1 MB


class FileIOTool(BaseTool):
    """Read or write files within whitelisted directories."""

    name = "file_io"
    description = (
        "Read or write text files. Only paths within allowed directories are permitted. "
        "Set operation='read' to read a file, 'write' to create/overwrite one."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["read", "write"],
                "description": "Whether to read or write.",
            },
            "path": {"type": "string", "description": "Absolute file path."},
            "content": {
                "type": "string",
                "description": "Content to write (only for operation='write').",
            },
        },
        "required": ["operation", "path"],
    }
    is_destructive = True  # write operations modify the filesystem

    def __init__(self, allowed_paths: list[str], max_size_bytes: int = _MAX_FILE_SIZE) -> None:
        self._allowed: list[Path] = [Path(p).resolve() for p in allowed_paths]
        self._max_size = max_size_bytes

    def _check_path(self, path: str) -> Path:
        resolved = Path(path).resolve()
        for allowed in self._allowed:
            try:
                resolved.relative_to(allowed)
                return resolved
            except ValueError:
                continue
        allowed_str = ", ".join(str(p) for p in self._allowed)
        raise ToolError(self.name, f"Path '{path}' is not within allowed directories: {allowed_str}")

    async def execute(self, **kwargs: Any) -> str:
        operation: str = kwargs["operation"]
        path_str: str = kwargs["path"]

        safe_path = self._check_path(path_str)

        with TOOL_LATENCY.labels(tool=self.name).time():
            if operation == "read":
                result = await self._read(safe_path)
            elif operation == "write":
                content: str = kwargs.get("content", "")
                result = await self._write(safe_path, content)
            else:
                raise ToolError(self.name, f"Unknown operation: {operation}")

        TOOL_CALLS.labels(tool=self.name, outcome="success").inc()
        return result

    async def _read(self, path: Path) -> str:
        if not path.exists():
            raise ToolError(self.name, f"File not found: {path}")
        if path.stat().st_size > self._max_size:
            raise ToolError(self.name, f"File too large (>{self._max_size} bytes)")
        content = await asyncio.to_thread(path.read_text, encoding="utf-8", errors="replace")
        return f"[{path}]\n{content}"

    async def _write(self, path: Path, content: str) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_text, content, encoding="utf-8")
        return f"Written {len(content)} characters to {path}"
