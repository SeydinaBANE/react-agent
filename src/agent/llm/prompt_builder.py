from __future__ import annotations

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
    """Convert goal + completed steps into the Anthropic messages format."""
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": f"Goal: {goal}"},
    ]

    for step in steps:
        # Assistant turn: thought + tool_use
        assistant_content: list[dict[str, Any]] = []
        if step.thought:
            assistant_content.append({"type": "text", "text": step.thought})

        # We store a synthetic tool_use_id derived from iteration number
        tool_use_id = f"tool_call_{step.iteration}"
        assistant_content.append(
            {
                "type": "tool_use",
                "id": tool_use_id,
                "name": step.action.tool,
                "input": step.action.input,
            }
        )
        messages.append({"role": "assistant", "content": assistant_content})

        # User turn: tool result
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": step.observation,
                    }
                ],
            }
        )

    return messages
