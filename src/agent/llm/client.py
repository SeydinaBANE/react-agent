from __future__ import annotations

import json
import time
from typing import Any

import openai
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from agent.core.exceptions import LLMError
from agent.core.schemas import Action
from agent.core.telemetry import LLM_LATENCY, get_logger

logger = get_logger(__name__)

_FINAL_ANSWER_TOOL = "final_answer"


class LLMClient:
    """Async LLM client targeting OpenRouter (OpenAI-compatible API).

    Uses function/tool calling to produce structured Thought + Action.
    The caller passes tool definitions; the model responds with either
    a tool call (= Action) or the special `final_answer` call.
    """

    def __init__(self, api_key: str, model: str, base_url: str = "https://openrouter.ai/api/v1") -> None:
        self._client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self._model = model

    @retry(
        retry=retry_if_exception_type((openai.RateLimitError, openai.APIStatusError)),
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
        """Call the model and return (thought, action).

        The model is instructed to always call a tool. When done, it calls
        `final_answer` with field `answer: str`.
        """
        all_tools = [*tool_schemas, _final_answer_tool_schema()]
        openai_tools = [_to_openai_tool(t) for t in all_tools]

        # Prepend system message
        full_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *messages,
        ]

        start = time.perf_counter()
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=full_messages,  # type: ignore[arg-type]
                tools=openai_tools,  # type: ignore[arg-type]
                tool_choice="required",
                max_tokens=max_tokens,
            )
        except openai.RateLimitError as exc:
            raise LLMError("Rate limit hit", status_code=429) from exc
        except openai.APIStatusError as exc:
            raise LLMError(str(exc), status_code=exc.status_code) from exc
        except openai.APIError as exc:
            raise LLMError(str(exc)) from exc
        finally:
            elapsed = time.perf_counter() - start
            LLM_LATENCY.observe(elapsed)

        thought, action = _parse_response(response)
        logger.debug(
            "llm_response",
            thought=thought[:120],
            tool=action.tool,
            finish_reason=response.choices[0].finish_reason,
        )
        return thought, action


def _to_openai_tool(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert our internal tool schema to OpenAI function tool format."""
    function_def: dict[str, Any] = {
        "name": schema["name"],
        "description": schema.get("description", ""),
        # Anthropic uses "input_schema", OpenAI uses "parameters"
        "parameters": schema.get("parameters", schema.get("input_schema", {"type": "object", "properties": {}})),
    }
    return {"type": "function", "function": function_def}


def _final_answer_tool_schema() -> dict[str, Any]:
    return {
        "name": _FINAL_ANSWER_TOOL,
        "description": (
            "Call this tool ONLY when you have fully completed the goal "
            "and have a final answer to give the user."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "answer": {"type": "string", "description": "The complete final answer."},
            },
            "required": ["answer"],
        },
    }


def _parse_response(response: openai.types.chat.ChatCompletion) -> tuple[str, Action]:
    choice = response.choices[0]
    message = choice.message

    thought: str = message.content or ""

    if not message.tool_calls:
        raise LLMError("Model returned no tool call — cannot extract action.")

    tool_call = message.tool_calls[0]
    tool_name = tool_call.function.name
    try:
        tool_input: dict[str, Any] = json.loads(tool_call.function.arguments)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Failed to parse tool arguments as JSON: {exc}") from exc

    return thought, Action(tool=tool_name, input=tool_input)
