"""Tests for LLM client and prompt builder (LLM fully mocked)."""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.exceptions import LLMError
from agent.core.schemas import Action, AgentStep
from agent.llm.client import LLMClient, _final_answer_tool_schema, _parse_response, _to_openai_tool
from agent.llm.prompt_builder import build_messages, build_system_prompt


# ── prompt builder ────────────────────────────────────────────────────────────

class TestBuildSystemPrompt:
    def test_contains_max_iterations(self) -> None:
        prompt = build_system_prompt(max_iterations=10)
        assert "10" in prompt

    def test_no_memory_placeholder(self) -> None:
        prompt = build_system_prompt(max_iterations=5)
        assert "No relevant past observations" in prompt

    def test_memory_snippets_injected(self) -> None:
        prompt = build_system_prompt(max_iterations=5, memory_snippets=["Found paper A", "Found paper B"])
        assert "Found paper A" in prompt
        assert "Found paper B" in prompt


class TestBuildMessages:
    def test_first_message_is_goal(self) -> None:
        msgs = build_messages("Research RAG", steps=[])
        assert msgs[0]["role"] == "user"
        assert "Research RAG" in msgs[0]["content"]

    def test_step_produces_assistant_and_tool_turns(self) -> None:
        step = AgentStep(
            iteration=1,
            thought="I should search",
            action=Action(tool="web_search", input={"query": "test"}),
            observation="Found 3 results",
            latency_ms=100,
        )
        msgs = build_messages("goal", steps=[step])
        # [user(goal), assistant(tool_calls), tool(result)]
        assert len(msgs) == 3
        assert msgs[1]["role"] == "assistant"
        assert msgs[2]["role"] == "tool"

    def test_tool_call_id_matches_result_id(self) -> None:
        step = AgentStep(
            iteration=2,
            thought="Searching",
            action=Action(tool="web_search", input={"query": "x"}),
            observation="result",
            latency_ms=50,
        )
        msgs = build_messages("goal", steps=[step])
        tool_call_id = msgs[1]["tool_calls"][0]["id"]
        result_id = msgs[2]["tool_call_id"]
        assert tool_call_id == result_id

    def test_tool_input_serialized_as_json(self) -> None:
        step = AgentStep(
            iteration=1,
            thought="t",
            action=Action(tool="web_search", input={"query": "RAG", "max_results": 5}),
            observation="o",
            latency_ms=0,
        )
        msgs = build_messages("goal", steps=[step])
        args_str = msgs[1]["tool_calls"][0]["function"]["arguments"]
        args = json.loads(args_str)
        assert args["query"] == "RAG"
        assert args["max_results"] == 5


# ── tool schema conversion ────────────────────────────────────────────────────

class TestToOpenaiTool:
    def test_wraps_in_function_type(self) -> None:
        schema = {
            "name": "web_search",
            "description": "Search the web",
            "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
        }
        openai_tool = _to_openai_tool(schema)
        assert openai_tool["type"] == "function"
        assert openai_tool["function"]["name"] == "web_search"
        assert "parameters" in openai_tool["function"]

    def test_uses_parameters_key_if_present(self) -> None:
        schema = {
            "name": "my_tool",
            "description": "desc",
            "parameters": {"type": "object", "properties": {}},
        }
        openai_tool = _to_openai_tool(schema)
        assert openai_tool["function"]["parameters"] == {"type": "object", "properties": {}}


class TestFinalAnswerSchema:
    def test_has_required_fields(self) -> None:
        schema = _final_answer_tool_schema()
        assert schema["name"] == "final_answer"
        assert "answer" in schema["parameters"]["properties"]
        assert "answer" in schema["parameters"]["required"]


# ── _parse_response ───────────────────────────────────────────────────────────

def _make_mock_response(tool_name: str, tool_input: dict[str, Any], thought: str = "") -> Any:
    tool_call = MagicMock()
    tool_call.function.name = tool_name
    tool_call.function.arguments = json.dumps(tool_input)

    message = MagicMock()
    message.content = thought
    message.tool_calls = [tool_call]

    choice = MagicMock()
    choice.message = message
    choice.finish_reason = "tool_calls"

    response = MagicMock()
    response.choices = [choice]
    return response


class TestParseResponse:
    def test_parses_tool_call(self) -> None:
        resp = _make_mock_response("web_search", {"query": "RAG"}, thought="Let me search")
        thought, action = _parse_response(resp)
        assert thought == "Let me search"
        assert action.tool == "web_search"
        assert action.input == {"query": "RAG"}

    def test_raises_if_no_tool_calls(self) -> None:
        message = MagicMock()
        message.content = "Just text"
        message.tool_calls = None
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        with pytest.raises(LLMError):
            _parse_response(response)

    def test_final_answer_parsed(self) -> None:
        resp = _make_mock_response("final_answer", {"answer": "Done!"})
        _, action = _parse_response(resp)
        assert action.tool == "final_answer"
        assert action.input["answer"] == "Done!"


# ── LLMClient.call (mock OpenAI SDK) ─────────────────────────────────────────

class TestLLMClient:
    @pytest.fixture
    def client(self) -> LLMClient:
        return LLMClient(
            api_key="sk-or-test",
            model="anthropic/claude-3.5-sonnet",
            base_url="https://openrouter.ai/api/v1",
        )

    @pytest.mark.asyncio
    async def test_call_returns_thought_and_action(self, client: LLMClient) -> None:
        mock_response = _make_mock_response("web_search", {"query": "test"}, thought="Searching")

        with patch.object(client._client.chat.completions, "create", new=AsyncMock(return_value=mock_response)):
            thought, action = await client.call(
                messages=[{"role": "user", "content": "Goal: test"}],
                system_prompt="system",
                tool_schemas=[],
            )

        assert thought == "Searching"
        assert action.tool == "web_search"

    @pytest.mark.asyncio
    async def test_raises_llm_error_on_api_error(self, client: LLMClient) -> None:
        import openai as oai

        with patch.object(
            client._client.chat.completions,
            "create",
            new=AsyncMock(side_effect=oai.APIError("error", request=MagicMock(), body=None)),
        ):
            with pytest.raises(LLMError):
                await client.call(
                    messages=[{"role": "user", "content": "goal"}],
                    system_prompt="system",
                    tool_schemas=[],
                )
