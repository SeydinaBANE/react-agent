"""Integration test: full ReAct loop end-to-end with real Qdrant, mocked LLM.

Requires Docker for Qdrant. LLM is mocked to avoid real API calls.
Run with: pytest tests/integration/ -v
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("testcontainers", reason="testcontainers not installed")

from testcontainers.qdrant import QdrantContainer  # type: ignore[import-untyped]


@pytest.fixture(scope="module")
def qdrant_container() -> Any:
    with QdrantContainer() as qdrant:
        yield qdrant


@pytest.mark.integration
@pytest.mark.asyncio
async def test_react_loop_completes_with_real_memory(qdrant_container: Any) -> None:
    from qdrant_client import AsyncQdrantClient

    from agent.core.schemas import TaskTrace
    from agent.memory.embedder import Embedder
    from agent.memory.episodic import EpisodicMemory
    from agent.runner.approval_gate import ApprovalGate
    from agent.runner.react_loop import ReactLoop
    from agent.runner.tracer import Tracer
    from agent.tools.base import ToolRegistry
    from agent.tools.code_executor import CodeExecutorTool

    # Real Qdrant
    client_info = qdrant_container.get_client()
    host = qdrant_container.get_container_host_ip()
    port = qdrant_container.get_exposed_port(6333)
    qdrant = AsyncQdrantClient(host=host, port=int(port))
    embedder = Embedder()
    memory = EpisodicMemory(qdrant, embedder, "integration_test")
    await memory.ensure_collection()

    # Real tools (code executor only)
    registry = ToolRegistry()
    registry.register(CodeExecutorTool(timeout_s=5))

    # Mock LLM: one tool call then final answer
    from agent.core.schemas import Action

    call_count = 0

    async def mock_llm_call(**kwargs: Any) -> tuple[str, Action]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "Let me compute", Action(tool="code_executor", input={"code": "print(6 * 7)"})
        return "Done", Action(tool="final_answer", input={"answer": "6 x 7 = 42"})

    llm = MagicMock()
    llm.call = mock_llm_call

    loop = ReactLoop(
        llm=llm,
        registry=registry,
        memory=memory,
        gate=ApprovalGate(),
        max_iterations=10,
    )
    trace = TaskTrace(goal="Calculate 6 multiplied by 7")
    tracer = Tracer(trace)

    wm = await loop.run(trace, tracer)

    assert wm.status == "completed"
    assert "42" in (wm.trace.final_answer or "")
    assert wm.iteration == 1

    await qdrant.close()
