from __future__ import annotations

import time
from typing import Any

import anthropic
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from agent.core.exceptions import LLMError
from agent.core.schemas import Action, AgentStep
from agent.core.telemetry import LLM_LATENCY, get_logger

logger = get_logger(__name__)

_FINAL_ANSWER_TOOL = "final_answer"


class LLMClient:
    """Thin async wrapper around the Anthropic SDK.

    Uses Claude's native tool_use to produce structured Thought + Action.
    The caller passes a list of tool definitions (JSON schemas); Claude
    responds with either a tool_use block (= Action) or a final_answer call.
    """

    def __init__(self, api_key: str, model: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    @retry(
        retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APIStatusError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def call(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tool_schemas: list[dict[str, Any]],
        max_tokens: int = 2048,
    ) -> tuple[str, Action]:
        """Call Claude and return (thought, action).

        Claude is instructed to always use a tool. If the task is done, it
        calls the special `final_answer` tool with field `answer: str`.
        """
        tools = [*tool_schemas, _final_answer_tool_schema()]

        start = time.perf_counter()
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=messages,
                tools=tools,  # type: ignore[arg-type]
                tool_choice={"type": "any"},
            )
        except anthropic.RateLimitError as exc:
            raise LLMError("Rate limit hit", status_code=429) from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(str(exc), status_code=exc.status_code) from exc
        except anthropic.APIError as exc:
            raise LLMError(str(exc)) from exc
        finally:
            elapsed = time.perf_counter() - start
            LLM_LATENCY.observe(elapsed)

        thought, action = _parse_response(response)
        logger.debug(
            "llm_response",
            thought=thought[:120],
            tool=action.tool,
            stop_reason=response.stop_reason,
        )
        return thought, action


def _final_answer_tool_schema() -> dict[str, Any]:
    return {
        "name": _FINAL_ANSWER_TOOL,
        "description": (
            "Call this tool ONLY when you have fully completed the goal "
            "and have a final answer to give the user."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "answer": {"type": "string", "description": "The complete final answer."},
            },
            "required": ["answer"],
        },
    }


def _parse_response(response: anthropic.types.Message) -> tuple[str, Action]:
    thought = ""
    tool_name: str | None = None
    tool_input: dict[str, Any] = {}

    for block in response.content:
        if block.type == "text":
            thought = block.text
        elif block.type == "tool_use":
            tool_name = block.name
            tool_input = dict(block.input)  # type: ignore[arg-type]

    if tool_name is None:
        raise LLMError("Claude returned no tool_use block — cannot extract action.")

    is_destructive = tool_input.pop("__destructive__", False)
    return thought, Action(
        tool=tool_name,
        input=tool_input,
        is_destructive=bool(is_destructive),
    )


def build_tool_result_message(
    step: AgentStep,
    tool_use_id: str,
) -> dict[str, Any]:
    """Build the assistant+user message pair needed to continue the conversation."""
    return {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": step.observation,
            }
        ],
    }
