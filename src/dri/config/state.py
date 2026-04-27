"""
Local CLI state — persists the active company ID between invocations.

Stored in `.dri_state` at the project root (gitignored).
This is intentionally a simple key-value file, not a DB record,
because it is a local UI preference, not business data.
"""
from __future__ import annotations

import json
from pathlib import Path

_STATE_FILE = Path(__file__).parent.parent.parent.parent / ".dri_state"


def _load() -> dict:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(data: dict) -> None:
    _STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_active_company_id() -> str | None:
    return _load().get("active_company_id")


def set_active_company_id(company_id: str) -> None:
    data = _load()
    data["active_company_id"] = company_id
    _save(data)


def clear_active_company() -> None:
    data = _load()
    data.pop("active_company_id", None)
    _save(data)
