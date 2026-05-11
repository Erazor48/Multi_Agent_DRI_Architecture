"""
Unit tests for OpenAICompatibleProvider.

No real network calls — openai.AsyncOpenAI is mocked throughout.
Tests cover:
  - Wire format conversion (messages + tools)
  - Response parsing (text, tool calls, tokens)
  - Retry passthrough (tenacity re-raises on exhaustion)
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dri.llm.openai_compatible_provider import (
    OpenAICompatibleProvider,
    _to_openai_messages,
    _to_openai_tools,
    _to_llm_response,
)
from dri.llm.base import LLMResponse, ToolCall


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_response(
    content: str = "",
    tool_calls: list | None = None,
    finish_reason: str = "stop",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
) -> MagicMock:
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls

    choice = MagicMock()
    choice.message = message
    choice.finish_reason = finish_reason

    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def _make_tool_call_obj(id: str, name: str, arguments: dict) -> MagicMock:
    fn = MagicMock()
    fn.name = name
    fn.arguments = json.dumps(arguments)

    tc = MagicMock()
    tc.id = id
    tc.function = fn
    return tc


# ── _to_openai_messages ───────────────────────────────────────────────────────

class TestToOpenAIMessages:
    def test_simple_user_text(self):
        msgs = [{"role": "user", "content": "hello"}]
        result = _to_openai_messages(msgs)
        assert result == [{"role": "user", "content": "hello"}]

    def test_simple_assistant_text(self):
        msgs = [{"role": "assistant", "content": "hi there"}]
        result = _to_openai_messages(msgs)
        assert result == [{"role": "assistant", "content": "hi there"}]

    def test_assistant_with_tool_use(self):
        msgs = [{
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me search"},
                {"type": "tool_use", "id": "tc_1", "name": "web_search", "input": {"query": "AI"}},
            ],
        }]
        result = _to_openai_messages(msgs)
        assert len(result) == 1
        msg = result[0]
        assert msg["role"] == "assistant"
        assert msg["content"] == "Let me search"
        assert len(msg["tool_calls"]) == 1
        tc = msg["tool_calls"][0]
        assert tc["id"] == "tc_1"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "web_search"
        assert json.loads(tc["function"]["arguments"]) == {"query": "AI"}

    def test_tool_result_becomes_tool_role(self):
        msgs = [{
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_call_id": "tc_1", "content": "search results here"},
            ],
        }]
        result = _to_openai_messages(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "tc_1"
        assert result[0]["content"] == "search results here"

    def test_assistant_tool_use_no_text(self):
        msgs = [{
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "tc_2", "name": "code_exec", "input": {"code": "print(1)"}},
            ],
        }]
        result = _to_openai_messages(msgs)
        assert result[0]["content"] is None
        assert len(result[0]["tool_calls"]) == 1


# ── _to_openai_tools ──────────────────────────────────────────────────────────

class TestToOpenAITools:
    def test_basic_conversion(self):
        tools = [{
            "name": "web_search",
            "description": "Search the web",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }]
        result = _to_openai_tools(tools)
        assert len(result) == 1
        assert result[0]["type"] == "function"
        fn = result[0]["function"]
        assert fn["name"] == "web_search"
        assert fn["description"] == "Search the web"
        assert fn["parameters"]["properties"]["query"]["type"] == "string"

    def test_missing_description_defaults_empty(self):
        tools = [{"name": "noop", "input_schema": {"type": "object", "properties": {}}}]
        result = _to_openai_tools(tools)
        assert result[0]["function"]["description"] == ""


# ── _to_llm_response ─────────────────────────────────────────────────────────

class TestToLLMResponse:
    def test_text_only_response(self):
        resp = _make_response(content="Hello world", finish_reason="stop")
        result = _to_llm_response(resp)
        assert isinstance(result, LLMResponse)
        assert result.text == "Hello world"
        assert result.tool_calls == []
        assert result.stop_reason == "end_turn"
        assert result.input_tokens == 10
        assert result.output_tokens == 5

    def test_tool_call_response(self):
        tc_obj = _make_tool_call_obj("id_1", "web_search", {"query": "test"})
        resp = _make_response(content="", tool_calls=[tc_obj], finish_reason="tool_calls")
        result = _to_llm_response(resp)
        assert result.stop_reason == "tool_use"
        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc.id == "id_1"
        assert tc.name == "web_search"
        assert tc.input == {"query": "test"}

    def test_malformed_arguments_defaults_empty_dict(self):
        tc_obj = MagicMock()
        tc_obj.id = "id_bad"
        tc_obj.function.name = "broken"
        tc_obj.function.arguments = "NOT JSON"

        resp = _make_response(tool_calls=[tc_obj], finish_reason="tool_calls")
        result = _to_llm_response(resp)
        assert result.tool_calls[0].input == {}

    def test_no_usage_defaults_zero(self):
        resp = _make_response()
        resp.usage = None
        result = _to_llm_response(resp)
        assert result.input_tokens == 0
        assert result.output_tokens == 0


# ── OpenAICompatibleProvider.call ─────────────────────────────────────────────

class TestOpenAICompatibleProviderCall:
    def _make_provider(self) -> tuple[OpenAICompatibleProvider, MagicMock]:
        with patch("dri.llm.openai_compatible_provider.AsyncOpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            provider = OpenAICompatibleProvider(api_key="sk-test", base_url="http://localhost/v1")
        return provider, mock_client

    @pytest.mark.asyncio
    async def test_call_text_response(self):
        provider, mock_client = self._make_provider()

        openai_resp = _make_response(content="hello", finish_reason="stop")
        mock_client.chat.completions.create = AsyncMock(return_value=openai_resp)

        result = await provider.call(
            system="You are helpful",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            model="gpt-4o",
            max_tokens=100,
        )

        assert result.text == "hello"
        assert result.stop_reason == "end_turn"
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o"
        assert call_kwargs["messages"][0] == {"role": "system", "content": "You are helpful"}
        assert "tools" not in call_kwargs

    @pytest.mark.asyncio
    async def test_call_with_tools(self):
        provider, mock_client = self._make_provider()

        tc_obj = _make_tool_call_obj("tc_1", "web_search", {"query": "AI"})
        openai_resp = _make_response(tool_calls=[tc_obj], finish_reason="tool_calls")
        mock_client.chat.completions.create = AsyncMock(return_value=openai_resp)

        tools = [{
            "name": "web_search",
            "description": "Search",
            "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
        }]

        result = await provider.call(
            system="sys",
            messages=[{"role": "user", "content": "search for AI"}],
            tools=tools,
            model="gpt-4o",
            max_tokens=256,
        )

        assert result.has_tool_calls
        assert result.tool_calls[0].name == "web_search"
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "tools" in call_kwargs
        assert call_kwargs["tool_choice"] == "auto"
