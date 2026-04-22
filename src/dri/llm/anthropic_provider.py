"""
Anthropic Claude provider.
Converts our wire format ↔ Anthropic SDK format.
"""
from __future__ import annotations

from typing import Any

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from dri.llm.base import BaseLLMProvider, LLMResponse, ToolCall


class AnthropicProvider(BaseLLMProvider):
    def __init__(self, api_key: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

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
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            # Prompt caching on the system prompt
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": self._to_anthropic_messages(messages),
        }
        if tools:
            kwargs["tools"] = tools  # already in Anthropic format

        response = await self._client.messages.create(**kwargs)
        return self._to_llm_response(response)

    # ── Conversion helpers ────────────────────────────────────────────────

    @staticmethod
    def _to_anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Our wire format is already Anthropic-compatible — pass through."""
        return messages

    @staticmethod
    def _to_llm_response(response: anthropic.types.Message) -> LLMResponse:
        text = ""
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                text = block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input or {}))

        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            stop_reason="tool_use" if tool_calls else "end_turn",
        )
