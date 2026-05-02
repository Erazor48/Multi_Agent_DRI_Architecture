"""
Test fixtures shared across all tests.
Uses an in-memory SQLite DB so tests never touch the real DB.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest
import pytest_asyncio

# Force-override DATABASE_URL so tests NEVER touch the production DB,
# regardless of when settings.py was imported.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ.setdefault("LLM_PROVIDER", "gemini")
os.environ.setdefault("GOOGLE_API_KEY", "test-google-key-not-real")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("WORKSPACE_DIR", "./test_workspace")
os.environ.setdefault("BUDGET_MAX_TOKENS_PER_SESSION", "100000")

# Clear lru_cache on settings so that the first call inside tests re-reads os.environ
# (which already has DATABASE_URL=:memory:). This is safe even if settings.py was
# already imported before this conftest module ran.
from dri.config.settings import get_settings as _get_settings_fn
_get_settings_fn.cache_clear()


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def db_session():
    """Provide a clean in-memory DB session for each test.

    Forces both settings cache and engine to re-initialize with DATABASE_URL=:memory:
    before each test, guaranteeing the production DB file is never touched.
    """
    from dri.config.settings import get_settings
    from dri.storage.database import drop_db, get_session, init_db, reset_engine
    # Ensure settings cache returns :memory: URL (not the production DB from .env)
    get_settings.cache_clear()
    reset_engine(test_db_url="sqlite+aiosqlite:///:memory:")
    await init_db()
    async with get_session() as session:
        yield session
    await drop_db()
    reset_engine()
    get_settings.cache_clear()  # restore clean state for next test


# ──────────────────────────────────────────────────────────────────────────────
# MockLLMProvider — scripted responses for integration tests
# ──────────────────────────────────────────────────────────────────────────────

class MockLLMProvider:
    """
    Scripted LLM provider for integration and unit tests.
    Returns responses from the queue; falls back to a plain text response.
    """

    def __init__(self, responses: list[Any] | None = None) -> None:
        from dri.llm.base import LLMResponse
        self._responses: list[Any] = responses or []
        self._fallback = LLMResponse(text="(mock response)")
        self._call_count = 0

    async def call(
        self,
        *,
        system: str,
        messages: list[dict],
        tools: list[dict] | None,
        model: str,
        max_tokens: int,
    ) -> Any:
        if self._call_count < len(self._responses):
            r = self._responses[self._call_count]
        else:
            r = self._fallback
        self._call_count += 1
        return r


def make_tool_response(tool_name: str, tool_input: dict) -> Any:
    """Build a LLMResponse with a single tool call."""
    from dri.llm.base import LLMResponse, ToolCall
    return LLMResponse(
        text="",
        tool_calls=[ToolCall(id="tc-mock-1", name=tool_name, input=tool_input)],
        input_tokens=100,
        output_tokens=200,
        stop_reason="tool_use",
    )


def make_text_response(text: str) -> Any:
    """Build a LLMResponse with plain text."""
    from dri.llm.base import LLMResponse
    return LLMResponse(text=text, input_tokens=50, output_tokens=100)
