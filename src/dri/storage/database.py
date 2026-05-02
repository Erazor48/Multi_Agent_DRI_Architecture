"""
Async SQLAlchemy engine + session factory.
Single point of configuration for all DB access.

The engine is initialized lazily (on first use of init_db / get_session) so that
test fixtures can override DATABASE_URL via os.environ before the engine is created.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from dri.storage.orm import Base

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

_engine: "AsyncEngine | None" = None
_session_factory: "async_sessionmaker[AsyncSession] | None" = None
_override_db_url: str | None = None  # set by tests to force a specific URL


def _get_engine() -> "AsyncEngine":
    global _engine, _session_factory
    if _engine is None:
        if _override_db_url is not None:
            db_url = _override_db_url
        else:
            from dri.config.settings import get_settings
            db_url = get_settings().database_url
        _engine = create_async_engine(db_url, echo=False, pool_pre_ping=True)
        _session_factory = async_sessionmaker(
            bind=_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    return _engine


def reset_engine(test_db_url: str | None = None) -> None:
    """Discard the cached engine. When test_db_url is given, the next engine will use that URL.
    Call with test_db_url=':memory:' in tests to guarantee isolation from the production DB.
    """
    global _engine, _session_factory, _override_db_url
    _engine = None
    _session_factory = None
    _override_db_url = test_db_url


async def init_db() -> None:
    """Create all tables. Call once at startup."""
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_db() -> None:
    """Drop all tables. Tests only."""
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager yielding a transactional session."""
    _get_engine()  # ensure factory is initialized
    assert _session_factory is not None
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
