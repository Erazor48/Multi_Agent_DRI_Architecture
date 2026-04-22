"""
Tool base class and global tool registry.
All tools are async, validated with Pydantic, and logged.
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class ToolInput(BaseModel):
    """Base for all tool input schemas."""


class ToolOutput(BaseModel):
    """Structured result from a tool call."""

    success: bool
    data: Any = None
    error: str | None = None
    call_id: str = ""

    @classmethod
    def ok(cls, data: Any, call_id: str = "") -> "ToolOutput":
        return cls(success=True, data=data, call_id=call_id or str(uuid.uuid4()))

    @classmethod
    def fail(cls, error: str, call_id: str = "") -> "ToolOutput":
        return cls(success=False, error=error, call_id=call_id or str(uuid.uuid4()))


class BaseTool(ABC):
    """
    Abstract base for all executable tools.
    Subclasses define name, description, input_schema, and execute().
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool identifier used in allowed_tools lists and Claude tool_use API."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description injected into agent prompts."""

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema for the tool's input (for Claude tool_use API)."""

    @abstractmethod
    async def execute(self, raw_input: dict[str, Any]) -> ToolOutput:
        """Execute the tool with validated input."""

    def to_claude_tool_spec(self) -> dict[str, Any]:
        """Format this tool for the Anthropic tool_use API."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolRegistry:
    """
    Global registry of all available tools.
    Agents receive a filtered subset based on their allowed_tools list.
    """

    _tools: dict[str, BaseTool] = {}

    @classmethod
    def register(cls, tool: BaseTool) -> None:
        cls._tools[tool.name] = tool

    @classmethod
    def get(cls, name: str) -> BaseTool:
        tool = cls._tools.get(name)
        if tool is None:
            raise KeyError(f"Tool '{name}' not registered. Available: {list(cls._tools)}")
        return tool

    @classmethod
    def get_many(cls, names: list[str]) -> list[BaseTool]:
        return [cls.get(n) for n in names if n in cls._tools]

    @classmethod
    def all(cls) -> list[BaseTool]:
        return list(cls._tools.values())

    @classmethod
    def names(cls) -> list[str]:
        return list(cls._tools.keys())

    @classmethod
    def to_claude_specs(cls, allowed: list[str]) -> list[dict[str, Any]]:
        """Return Claude-format tool specs for the given allowed tool names."""
        return [cls.get(n).to_claude_tool_spec() for n in allowed if n in cls._tools]
