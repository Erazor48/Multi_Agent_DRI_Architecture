"""
Test fixtures shared across all tests.
Uses an in-memory SQLite DB so tests never touch the real DB.
"""
from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("WORKSPACE_DIR", "./test_workspace")
os.environ.setdefault("BUDGET_MAX_TOKENS_PER_SESSION", "100000")


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def db_session():
    """Provide a clean in-memory DB session for each test."""
    from dri.storage.database import drop_db, get_session, init_db
    await init_db()
    async with get_session() as session:
        yield session
    await drop_db()
