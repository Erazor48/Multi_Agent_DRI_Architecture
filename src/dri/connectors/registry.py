"""
ConnectorRegistry — maps approved actions to the right connector.

Connectors self-register at import time (same pattern as ToolRegistry).
The CLI calls `ConnectorRegistry.get_for(action_type, action)` after approval.
"""
from __future__ import annotations

from dri.connectors.base import BaseConnector


class ConnectorRegistry:
    _connectors: list[BaseConnector] = []

    @classmethod
    def register(cls, connector: BaseConnector) -> None:
        # Skip duplicates — safe to import connectors module multiple times (e.g. in tests).
        if not any(type(c) is type(connector) for c in cls._connectors):
            cls._connectors.append(connector)

    @classmethod
    def get_for(cls, action_type: str, action: dict) -> BaseConnector | None:
        """
        Return the first connector that can handle this action, or None.
        Connectors are evaluated in registration order.
        """
        for connector in cls._connectors:
            if connector.can_handle(action_type, action):
                return connector
        return None

    @classmethod
    def all_configured(cls) -> list[BaseConnector]:
        return [c for c in cls._connectors if c.is_configured]

    @classmethod
    def status(cls) -> list[dict]:
        """Return a list of connector status dicts for display."""
        return [
            {
                "connector": type(c).__name__,
                "configured": c.is_configured,
                "hint": c.setup_hint if not c.is_configured else "",
            }
            for c in cls._connectors
        ]
