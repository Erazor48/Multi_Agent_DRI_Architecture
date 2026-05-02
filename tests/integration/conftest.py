"""
Fixtures spécifiques aux tests d'intégration.
Charge le .env réel mais préserve DATABASE_URL en :memory: pour ne pas toucher la DB de prod.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load real .env for API keys (Gemini, Slack, etc.) but preserve DATABASE_URL override
# set by the root conftest.py so integration tests never touch the production DB.
_TEST_DB_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
load_dotenv(Path(__file__).parent.parent.parent / ".env", override=True)
os.environ["DATABASE_URL"] = _TEST_DB_URL  # restore :memory: after dotenv override


@pytest.fixture(autouse=True)
def reload_settings():
    """Vide le cache lru_cache de settings pour que les vars .env soient prises en compte."""
    from dri.config.settings import get_settings
    from dri.storage.database import reset_engine
    get_settings.cache_clear()
    reset_engine()
    yield
    get_settings.cache_clear()
    reset_engine()
