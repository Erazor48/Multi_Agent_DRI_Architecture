"""
LLM provider abstraction.

All LLM calls go through a BaseLLMProvider, never directly through a vendor SDK.
This keeps provider-specific code isolated so switching or adding providers
requires zero changes to agent logic.

Message format (our internal "wire format", used by BaseAgent):
    User text:
        {"role": "user", "content": "some text"}
    User tool results:
        {"role": "user", "content": [
            {"type": "tool_result", "tool_call_id": "id", "content": "result text"}
        ]}
    Assistant text:
        {"role": "assistant", "content": "some text"}
    Assistant text + tool calls:
        {"role": "assistant", "content": [
            {"type": "text", "text": "..."},
            {"type": "tool_use", "id": "id", "name": "tool_name", "input": {...}}
        ]}

Providers convert to/from this format in both directions.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """A tool call requested by the LLM."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResponse:
    """Normalized response from any LLM provider."""

    text: str                              # final text output (may be empty if only tool calls)
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = "end_turn"          # "end_turn" | "tool_use"

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    def to_assistant_message(self) -> dict[str, Any]:
        """Convert this response into an assistant message for the next turn."""
        if not self.has_tool_calls and self.text:
            return {"role": "assistant", "content": self.text}

        content: list[dict[str, Any]] = []
        if self.text:
            content.append({"type": "text", "text": self.text})
        for tc in self.tool_calls:
            content.append({
                "type": "tool_use",
                "id": tc.id,
                "name": tc.name,
                "input": tc.input,
            })
        return {"role": "assistant", "content": content}


class BaseLLMProvider(ABC):
    """Abstract LLM provider. One instance per agent (holds no conversation state)."""

    @abstractmethod
    async def call(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        max_tokens: int,
    ) -> LLMResponse:
        """
        Make one LLM call and return a normalized response.

        Args:
            system:     System prompt text.
            messages:   Conversation history in our wire format.
            tools:      Tool specs in Anthropic JSON-schema format (providers convert internally).
            model:      Provider-specific model identifier.
            max_tokens: Max output tokens.
        """
