"""Tests for LLM client and prompt builder (LLM fully mocked)."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.exceptions import LLMError
from agent.core.schemas import Action, AgentStep
from agent.llm.client import LLMClient, _final_answer_tool_schema, _parse_response
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

    def test_step_produces_assistant_and_user_turns(self) -> None:
        step = AgentStep(
            iteration=1,
            thought="I should search",
            action=Action(tool="web_search", input={"query": "test"}),
            observation="Found 3 results",
            latency_ms=100,
        )
        msgs = build_messages("goal", steps=[step])
        # [user(goal), assistant(tool_use), user(tool_result)]
        assert len(msgs) == 3
        assert msgs[1]["role"] == "assistant"
        assert msgs[2]["role"] == "user"

    def test_tool_use_id_matches_tool_result_id(self) -> None:
        step = AgentStep(
            iteration=2,
            thought="Searching",
            action=Action(tool="web_search", input={"query": "x"}),
            observation="result",
            latency_ms=50,
        )
        msgs = build_messages("goal", steps=[step])
        tool_use_id = msgs[1]["content"][-1]["id"]
        tool_result_id = msgs[2]["content"][0]["tool_use_id"]
        assert tool_use_id == tool_result_id


# ── final answer tool schema ──────────────────────────────────────────────────

class TestFinalAnswerSchema:
    def test_has_required_fields(self) -> None:
        schema = _final_answer_tool_schema()
        assert schema["name"] == "final_answer"
        assert "answer" in schema["input_schema"]["properties"]
        assert "answer" in schema["input_schema"]["required"]


# ── _parse_response ───────────────────────────────────────────────────────────

def _make_mock_response(tool_name: str, tool_input: dict[str, Any], thought: str = "") -> Any:
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = thought

    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = tool_name
    tool_block.input = tool_input

    response = MagicMock()
    response.content = [text_block, tool_block] if thought else [tool_block]
    response.stop_reason = "tool_use"
    return response


class TestParseResponse:
    def test_parses_tool_call(self) -> None:
        resp = _make_mock_response("web_search", {"query": "RAG"}, thought="Let me search")
        thought, action = _parse_response(resp)
        assert thought == "Let me search"
        assert action.tool == "web_search"
        assert action.input == {"query": "RAG"}

    def test_raises_if_no_tool_use(self) -> None:
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Just some text"
        response = MagicMock()
        response.content = [text_block]
        with pytest.raises(LLMError):
            _parse_response(response)

    def test_final_answer_parsed(self) -> None:
        resp = _make_mock_response("final_answer", {"answer": "Done!"})
        _, action = _parse_response(resp)
        assert action.tool == "final_answer"
        assert action.input["answer"] == "Done!"


# ── LLMClient.call (mock Anthropic SDK) ──────────────────────────────────────

class TestLLMClient:
    @pytest.fixture
    def client(self) -> LLMClient:
        return LLMClient(api_key="sk-test", model="claude-3-5-haiku-20241022")

    @pytest.mark.asyncio
    async def test_call_returns_thought_and_action(self, client: LLMClient) -> None:
        mock_response = _make_mock_response("web_search", {"query": "test"}, thought="Searching")

        with patch.object(client._client.messages, "create", new=AsyncMock(return_value=mock_response)):
            thought, action = await client.call(
                messages=[{"role": "user", "content": "Goal: test"}],
                system_prompt="system",
                tool_schemas=[],
            )

        assert thought == "Searching"
        assert action.tool == "web_search"

    @pytest.mark.asyncio
    async def test_raises_llm_error_on_api_error(self, client: LLMClient) -> None:
        import anthropic as ant

        with patch.object(
            client._client.messages,
            "create",
            new=AsyncMock(side_effect=ant.APIError("error", request=MagicMock(), body=None)),
        ):
            with pytest.raises(LLMError):
                await client.call(
                    messages=[{"role": "user", "content": "goal"}],
                    system_prompt="system",
                    tool_schemas=[],
                )
