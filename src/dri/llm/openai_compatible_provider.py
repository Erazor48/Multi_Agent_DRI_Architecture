"""
OpenAI-compatible provider.

Covers any endpoint that speaks the OpenAI Chat Completions API:
  - OpenAI (api.openai.com)
  - OpenRouter (openrouter.ai/api/v1)
  - Groq (api.groq.com/openai/v1)
  - Together AI (api.together.xyz/v1)
  - Ollama (localhost:11434/v1)
  - Fireworks, Anyscale, LM Studio, etc.

Wire format bridge:
  - Incoming messages: our Anthropic-style wire format
  - Outgoing to SDK: OpenAI Chat format
  - Incoming tools: Anthropic input_schema format
  - Outgoing tools to SDK: OpenAI function format
"""
from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from dri.llm.base import BaseLLMProvider, LLMResponse, ToolCall


class OpenAICompatibleProvider(BaseLLMProvider):
    def __init__(self, api_key: str, base_url: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30), reraise=True)
    async def call(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        max_tokens: int,
    ) -> LLMResponse:
        openai_messages = [{"role": "system", "content": system}] + _to_openai_messages(messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": openai_messages,
        }
        if tools:
            kwargs["tools"] = _to_openai_tools(tools)
            kwargs["tool_choice"] = "auto"

        response = await self._client.chat.completions.create(**kwargs)
        return _to_llm_response(response)


# ── Wire format converters ────────────────────────────────────────────────────

def _to_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert our Anthropic-style wire format to OpenAI Chat message list."""
    result: list[dict[str, Any]] = []

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if role == "user":
            if isinstance(content, str):
                result.append({"role": "user", "content": content})
            else:
                # List content — may contain tool_result blocks
                tool_results = [b for b in content if b.get("type") == "tool_result"]
                text_parts = [b for b in content if b.get("type") != "tool_result"]

                for block in tool_results:
                    result.append({
                        "role": "tool",
                        "tool_call_id": block["tool_call_id"],
                        "content": block.get("content", ""),
                    })
                if text_parts:
                    text = " ".join(b.get("text", "") for b in text_parts if b.get("type") == "text")
                    if text:
                        result.append({"role": "user", "content": text})

        elif role == "assistant":
            if isinstance(content, str):
                result.append({"role": "assistant", "content": content})
            else:
                # List content — may contain text + tool_use blocks
                text = ""
                tool_calls: list[dict[str, Any]] = []

                for block in content:
                    if block.get("type") == "text":
                        text = block.get("text", "")
                    elif block.get("type") == "tool_use":
                        tool_calls.append({
                            "id": block["id"],
                            "type": "function",
                            "function": {
                                "name": block["name"],
                                "arguments": json.dumps(block.get("input", {})),
                            },
                        })

                msg_out: dict[str, Any] = {"role": "assistant", "content": text or None}
                if tool_calls:
                    msg_out["tool_calls"] = tool_calls
                result.append(msg_out)

    return result


def _to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Anthropic-format tool specs to OpenAI function format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


def _to_llm_response(response: Any) -> LLMResponse:
    """Convert an OpenAI ChatCompletion response to LLMResponse."""
    choice = response.choices[0]
    message = choice.message

    text = message.content or ""
    tool_calls: list[ToolCall] = []

    if message.tool_calls:
        for tc in message.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, input=args))

    finish_reason = choice.finish_reason or "stop"
    stop_reason = "tool_use" if finish_reason == "tool_calls" else "end_turn"

    usage = response.usage
    return LLMResponse(
        text=text,
        tool_calls=tool_calls,
        input_tokens=usage.prompt_tokens if usage else 0,
        output_tokens=usage.completion_tokens if usage else 0,
        stop_reason=stop_reason,
    )
