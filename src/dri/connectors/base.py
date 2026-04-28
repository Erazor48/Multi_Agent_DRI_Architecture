"""
Base class for all real-world action connectors.

A connector takes an approved action (from _pending_approvals.json) and
executes it — sending an email, posting to Slack, hitting a webhook, etc.

Each connector declares which action_type(s) it handles and whether it is
currently configured (i.e., the required credentials are present in .env).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ConnectorResult:
    success: bool
    message: str
    external_id: str | None = None  # e.g., email message-id, Slack ts
    details: dict = field(default_factory=dict)


class BaseConnector(ABC):
    """
    Abstract base for a real-world action connector.

    Subclasses override:
    - `can_handle(action_type, action)` — True if this connector should run
    - `is_configured` — True if all required credentials are set
    - `setup_hint` — human-readable setup instructions
    - `execute(action)` — runs the action, returns ConnectorResult
    """

    @abstractmethod
    def can_handle(self, action_type: str, action: dict) -> bool:
        """Return True if this connector is able to handle the given action."""

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """True if all required credentials/settings are present in .env."""

    @property
    @abstractmethod
    def setup_hint(self) -> str:
        """One-line setup hint shown to the user when not configured."""

    @abstractmethod
    async def execute(self, action: dict) -> ConnectorResult:
        """
        Execute the approved action.

        `action` is the full dict from _pending_approvals.json, containing:
        - action_type, recipient, subject, content, rationale
        - proposed_by, company, proposed_at
        """
