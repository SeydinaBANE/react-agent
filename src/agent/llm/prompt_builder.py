from __future__ import annotations

import json
from typing import Any

from agent.core.schemas import AgentStep

_SYSTEM_PROMPT_TEMPLATE = """\
You are an autonomous AI agent that solves tasks step by step using the ReAct \
(Reasoning + Acting) pattern.

## Instructions
1. Think carefully about what to do next (your reasoning will appear as "thought").
2. Select exactly ONE tool and call it.
3. After observing the tool result, plan your next step.
4. When the task is fully completed, call the `final_answer` tool with the complete result.

## Constraints
- Always call a tool — never reply with plain text only.
- Maximum {max_iterations} iterations; be efficient.
- For destructive operations (writing files, deleting data), prefer to confirm first \
unless explicitly instructed otherwise.

## Relevant memory (past observations you may reuse)
{memory_context}
"""

_NO_MEMORY = "No relevant past observations found."


def build_system_prompt(
    max_iterations: int,
    memory_snippets: list[str] | None = None,
) -> str:
    if memory_snippets:
        memory_context = "\n".join(f"- {s}" for s in memory_snippets)
    else:
        memory_context = _NO_MEMORY

    return _SYSTEM_PROMPT_TEMPLATE.format(
        max_iterations=max_iterations,
        memory_context=memory_context,
    )


def build_messages(
    goal: str,
    steps: list[AgentStep],
) -> list[dict[str, Any]]:
    """Convert goal + completed steps into OpenAI-compatible messages format."""
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": f"Goal: {goal}"},
    ]

    for step in steps:
        tool_call_id = f"call_{step.iteration}"

        # Assistant turn: optional thought text + tool_calls array
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": step.thought or "",
            "tool_calls": [
                {
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": step.action.tool,
                        "arguments": json.dumps(step.action.input),
                    },
                }
            ],
        }
        messages.append(assistant_msg)

        # Tool result turn
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": step.observation,
            }
        )

    return messages
