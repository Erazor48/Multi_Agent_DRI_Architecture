"""
Fixtures spécifiques aux tests d'intégration.
Charge le .env réel et vide le cache settings avant chaque test live.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env", override=True)


@pytest.fixture(autouse=True)
def reload_settings():
    """Vide le cache lru_cache de settings pour que les vars .env soient prises en compte."""
    from dri.config.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
