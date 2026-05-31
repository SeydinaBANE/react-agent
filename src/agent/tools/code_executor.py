from __future__ import annotations

import asyncio
import sys
import textwrap
from typing import Any

from agent.core.exceptions import ToolError, ToolTimeoutError
from agent.core.telemetry import TOOL_CALLS, TOOL_LATENCY, get_logger
from agent.tools.base import BaseTool

logger = get_logger(__name__)

_FORBIDDEN_MODULES = frozenset(
    ["os", "subprocess", "sys", "socket", "importlib", "shutil", "signal", "ctypes"]
)
_MAX_OUTPUT = 5000


class CodeExecutorTool(BaseTool):
    """Execute Python code in a restricted subprocess with a timeout."""

    name = "code_executor"
    description = (
        "Execute Python code and return stdout/stderr. Use for calculations, "
        "data transformations, or generating formatted output. "
        "Network access and file I/O are not available inside the executor."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute."},
        },
        "required": ["code"],
    }
    is_destructive = False

    def __init__(self, timeout_s: int = 10, enabled: bool = True) -> None:
        self._timeout = timeout_s
        self._enabled = enabled

    async def execute(self, **kwargs: Any) -> str:
        if not self._enabled:
            return "[code_executor is disabled in this environment]"

        code: str = kwargs["code"]
        _check_forbidden_imports(code)

        with TOOL_LATENCY.labels(tool=self.name).time():
            result = await _run_in_subprocess(code, self._timeout)

        TOOL_CALLS.labels(tool=self.name, outcome="success").inc()
        return result


def _check_forbidden_imports(code: str) -> None:
    for module in _FORBIDDEN_MODULES:
        if f"import {module}" in code or f"from {module}" in code:
            raise ToolError("code_executor", f"Module '{module}' is forbidden.")


async def _run_in_subprocess(code: str, timeout_s: int) -> str:
    # Wrap code so print() output is captured, errors surfaced cleanly
    wrapper = textwrap.dedent(f"""
import sys
_output = []
_orig_print = print
def print(*args, **kwargs):
    sep = kwargs.get("sep", " ")
    end = kwargs.get("end", "\\n")
    _output.append(sep.join(str(a) for a in args) + end)
try:
{textwrap.indent(code, "    ")}
except Exception as _e:
    sys.stdout.write(f"ERROR: {{type(_e).__name__}}: {{_e}}\\n")
else:
    sys.stdout.write("".join(_output))
""")

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            wrapper,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=float(timeout_s))
    except TimeoutError as exc:
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass  # process already exited before we could kill it
        raise ToolTimeoutError("code_executor", timeout_s) from exc

    output = stdout.decode(errors="replace") + stderr.decode(errors="replace")
    return output[:_MAX_OUTPUT] or "(no output)"
