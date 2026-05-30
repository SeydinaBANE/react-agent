from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

from agent.core.exceptions import (
    AgentError,
    HumanApprovalRequired,
    MaxIterationsError,
    ToolError,
)
from agent.core.schemas import Action, AgentStep, TaskTrace
from agent.core.telemetry import (
    REACT_ITERATIONS,
    TASK_STATUS,
    get_logger,
)
from agent.llm.client import LLMClient
from agent.llm.prompt_builder import build_messages, build_system_prompt
from agent.memory.episodic import EpisodicMemory
from agent.memory.working import WorkingMemory
from agent.runner.approval_gate import ApprovalGate
from agent.runner.tracer import Tracer
from agent.tools.base import ToolRegistry

logger = get_logger(__name__)

_FINAL_ANSWER_TOOL = "final_answer"


class ReactLoop:
    """Orchestrates the Thought → Action → Observation loop for one task."""

    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        memory: EpisodicMemory,
        gate: ApprovalGate,
        max_iterations: int = 15,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._memory = memory
        self._gate = gate
        self._max_iterations = max_iterations

    async def run(self, trace: TaskTrace, tracer: Tracer) -> WorkingMemory:
        wm = WorkingMemory(trace)

        try:
            await self._loop(wm, tracer)
        except MaxIterationsError as exc:
            wm.set_failed(str(exc))
            tracer.record_error(str(exc))
            TASK_STATUS.labels(status="failed").inc()
        except AgentError as exc:
            wm.set_failed(str(exc))
            tracer.record_error(str(exc))
            TASK_STATUS.labels(status="failed").inc()
        except Exception as exc:
            wm.set_failed(f"Unexpected error: {exc}")
            tracer.record_error(str(exc))
            TASK_STATUS.labels(status="failed").inc()
            logger.exception("react_loop_unexpected_error", task_id=wm.task_id)

        REACT_ITERATIONS.observe(wm.iteration)
        return wm

    async def _loop(self, wm: WorkingMemory, tracer: Tracer) -> None:
        for _ in range(self._max_iterations):
            # Retrieve relevant memories
            memory_snippets = await self._memory.search(wm.goal, top_k=3)

            # Build prompt
            system_prompt = build_system_prompt(
                max_iterations=self._max_iterations,
                memory_snippets=memory_snippets or None,
            )
            messages = build_messages(wm.goal, wm.steps)

            # LLM call
            start = time.perf_counter()
            thought, action = await self._llm.call(
                messages=messages,
                system_prompt=system_prompt,
                tool_schemas=self._registry.all_schemas(),
            )
            llm_ms = int((time.perf_counter() - start) * 1000)

            # Check for final answer
            if action.tool == _FINAL_ANSWER_TOOL:
                answer = action.input.get("answer", "")
                wm.set_final_answer(answer)
                tracer.record_final(answer)
                TASK_STATUS.labels(status="completed").inc()
                logger.info("task_completed", task_id=wm.task_id, answer=answer[:80])
                return

            # Approval gate for destructive tools
            try:
                await self._gate.check(wm.task_id, action)
            except HumanApprovalRequired:
                wm.set_status("waiting_approval")
                tracer.record_waiting_approval(action.tool)

                approved = await self._gate.wait(wm.task_id)
                if not approved:
                    wm.set_failed("Human rejected the destructive action.")
                    tracer.record_error("Action rejected by human.")
                    TASK_STATUS.labels(status="failed").inc()
                    return
                wm.set_status("running")

            # Execute tool
            observation = await self._execute_tool(action)

            # Store observation in episodic memory
            await self._memory.store(
                observation,
                metadata={"task_id": wm.task_id, "tool": action.tool},
            )

            # Record step
            step = AgentStep(
                iteration=wm.iteration + 1,
                thought=thought,
                action=action,
                observation=observation,
                latency_ms=llm_ms,
            )
            wm.append_step(step)
            tracer.record_step(step)

        raise MaxIterationsError(
            f"Reached maximum iterations ({self._max_iterations}) without a final answer."
        )

    async def _execute_tool(self, action: Action) -> str:
        tool = self._registry.get(action.tool)
        try:
            return await tool.execute(**action.input)
        except ToolError as exc:
            logger.warning("tool_error", tool=action.tool, error=str(exc))
            # Return the error as observation so the LLM can recover
            return f"[Tool error] {exc}"
