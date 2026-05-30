"""Tests for all tools (all external calls mocked)."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.exceptions import ToolError, ToolNotFoundError, ToolTimeoutError
from agent.tools.base import BaseTool, ToolRegistry
from agent.tools.code_executor import CodeExecutorTool, _check_forbidden_imports
from agent.tools.file_io import FileIOTool
from agent.tools.http_client import HttpClientTool
from agent.tools.web_search import WebSearchTool


# ── ToolRegistry ──────────────────────────────────────────────────────────────

class TestToolRegistry:
    def _make_tool(self, name: str) -> BaseTool:
        t = BaseTool()
        t.name = name
        t.description = "test tool"
        t.input_schema = {"type": "object", "properties": {}}
        t.is_destructive = False
        return t

    def test_register_and_get(self) -> None:
        registry = ToolRegistry()
        tool = self._make_tool("my_tool")
        registry.register(tool)
        assert registry.get("my_tool") is tool

    def test_get_unknown_raises(self) -> None:
        registry = ToolRegistry()
        with pytest.raises(ToolNotFoundError):
            registry.get("nonexistent")

    def test_all_schemas(self) -> None:
        registry = ToolRegistry()
        registry.register(self._make_tool("tool_a"))
        registry.register(self._make_tool("tool_b"))
        schemas = registry.all_schemas()
        assert len(schemas) == 2
        names = {s["name"] for s in schemas}
        assert names == {"tool_a", "tool_b"}


# ── WebSearchTool ─────────────────────────────────────────────────────────────

class TestWebSearchTool:
    def test_no_api_key_returns_disabled_message(self) -> None:
        tool = WebSearchTool(api_key="")

        async def run() -> str:
            return await tool.execute(query="RAG papers")

        result = asyncio.get_event_loop().run_until_complete(run())
        assert "disabled" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_formatted_results(self) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "web": {
                "results": [
                    {"title": "Paper A", "url": "https://a.com", "description": "About RAG"},
                    {"title": "Paper B", "url": "https://b.com", "description": "Advanced RAG"},
                ]
            }
        }

        tool = WebSearchTool(api_key="test-key")
        with patch("agent.tools.web_search.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = await tool.execute(query="RAG papers", max_results=2)

        assert "Paper A" in result
        assert "Paper B" in result


# ── CodeExecutorTool ──────────────────────────────────────────────────────────

class TestCodeExecutorTool:
    @pytest.mark.asyncio
    async def test_basic_execution(self) -> None:
        tool = CodeExecutorTool(timeout_s=10)
        result = await tool.execute(code="print(2 + 2)")
        assert "4" in result

    @pytest.mark.asyncio
    async def test_disabled_returns_message(self) -> None:
        tool = CodeExecutorTool(enabled=False)
        result = await tool.execute(code="print('hello')")
        assert "disabled" in result.lower()

    def test_forbidden_import_raises(self) -> None:
        with pytest.raises(ToolError, match="forbidden"):
            _check_forbidden_imports("import os\nos.listdir('.')")

    @pytest.mark.asyncio
    async def test_timeout_raises(self) -> None:
        tool = CodeExecutorTool(timeout_s=1)
        with pytest.raises(ToolTimeoutError):
            await tool.execute(code="import time\ntime.sleep(60)")

    @pytest.mark.asyncio
    async def test_syntax_error_captured(self) -> None:
        tool = CodeExecutorTool(timeout_s=10)
        result = await tool.execute(code="print(")
        # subprocess will write to stderr, captured as output
        assert result  # non-empty, some error message


# ── FileIOTool ────────────────────────────────────────────────────────────────

class TestFileIOTool:
    @pytest.mark.asyncio
    async def test_write_and_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = FileIOTool(allowed_paths=[tmpdir])
            fpath = str(Path(tmpdir) / "test.txt")

            write_result = await tool.execute(operation="write", path=fpath, content="hello world")
            assert "Written" in write_result

            read_result = await tool.execute(operation="read", path=fpath)
            assert "hello world" in read_result

    @pytest.mark.asyncio
    async def test_path_outside_whitelist_raises(self) -> None:
        tool = FileIOTool(allowed_paths=["/tmp"])
        with pytest.raises(ToolError, match="not within"):
            await tool.execute(operation="read", path="/etc/passwd")

    @pytest.mark.asyncio
    async def test_read_nonexistent_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = FileIOTool(allowed_paths=[tmpdir])
            with pytest.raises(ToolError, match="not found"):
                await tool.execute(operation="read", path=str(Path(tmpdir) / "nope.txt"))


# ── HttpClientTool ────────────────────────────────────────────────────────────

class TestHttpClientTool:
    @pytest.mark.asyncio
    async def test_get_request(self) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"key": "value"}'

        tool = HttpClientTool()
        with patch("agent.tools.http_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = await tool.execute(url="https://api.example.com/data")

        assert "200" in result
        assert "key" in result

    @pytest.mark.asyncio
    async def test_url_not_in_whitelist_raises(self) -> None:
        tool = HttpClientTool(allowed_url_prefixes=["https://allowed.com"])
        with pytest.raises(ToolError, match="not in the allowed"):
            await tool.execute(url="https://evil.com/data")
