"""
SendGrid email connector — sends emails via the SendGrid Web API.

Takes priority over EmailSMTPConnector when SENDGRID_API_KEY is configured.
Better deliverability than direct SMTP (no port blocking, reputation management,
bounce/spam handling built-in).

Handles action_type = "email" — only when SENDGRID_API_KEY is set.
Falls back to EmailSMTPConnector automatically if this connector is unconfigured.

Setup (.env):
  SENDGRID_API_KEY=SG...              # required
  SENDGRID_FROM_EMAIL=you@example.com # must be verified in SendGrid
  SENDGRID_FROM_NAME=DRI Agent        # optional display name

SendGrid quick-start:
  1. Sign up at https://sendgrid.com (free tier: 100 emails/day)
  2. Settings → API Keys → Create API Key (Mail Send scope is sufficient)
  3. Settings → Sender Authentication → verify your sender email
"""
from __future__ import annotations

import asyncio

from dri.config.settings import settings
from dri.connectors.base import BaseConnector, ConnectorResult
from dri.connectors.registry import ConnectorRegistry


class SendGridEmailConnector(BaseConnector):
    """
    Sends emails via SendGrid for action_type = "email".
    Only active when SENDGRID_API_KEY + SENDGRID_FROM_EMAIL are set.
    If unconfigured, can_handle returns False so EmailSMTPConnector can handle the action.
    """

    def can_handle(self, action_type: str, action: dict) -> bool:
        # Only claim this action if we're actually configured — lets SMTP be the fallback.
        return action_type == "email" and settings.has_sendgrid

    @property
    def is_configured(self) -> bool:
        return settings.has_sendgrid

    @property
    def setup_hint(self) -> str:
        return (
            "Set SENDGRID_API_KEY and SENDGRID_FROM_EMAIL in .env. "
            "Get your API key at https://app.sendgrid.com/settings/api_keys. "
            "The sender email must be verified under Settings → Sender Authentication."
        )

    async def execute(self, action: dict) -> ConnectorResult:
        if not self.is_configured:
            return ConnectorResult(
                success=False,
                message=f"SendGrid connector not configured. {self.setup_hint}",
            )

        recipient = action.get("recipient", "").strip()
        if not recipient:
            return ConnectorResult(success=False, message="No recipient email address provided.")

        subject = (
            action.get("subject", "").strip()
            or f"Message from {action.get('company', 'DRI')} — {action.get('proposed_by', 'Agent')}"
        )
        content = action.get("content", "")

        try:
            result = await asyncio.to_thread(self._send_sync, recipient, subject, content)
            return result
        except Exception as e:
            return ConnectorResult(success=False, message=f"SendGrid send failed: {e}")

    def _send_sync(self, to: str, subject: str, body: str) -> ConnectorResult:
        try:
            from sendgrid import SendGridAPIClient  # type: ignore[import-untyped]
            from sendgrid.helpers.mail import Mail, To, From, Content  # type: ignore[import-untyped]
        except ImportError:
            return ConnectorResult(
                success=False,
                message="sendgrid package not installed. Run: uv sync",
            )

        message = Mail(
            from_email=From(settings.sendgrid_from_email, settings.sendgrid_from_name),
            to_emails=To(to),
            subject=subject,
            plain_text_content=Content("text/plain", body),
        )

        try:
            client = SendGridAPIClient(settings.sendgrid_api_key)
            response = client.send(message)

            if response.status_code in (200, 202):
                msg_id = response.headers.get("X-Message-Id", "")
                return ConnectorResult(
                    success=True,
                    message=f"Email sent to {to} via SendGrid (status={response.status_code}).",
                    external_id=msg_id,
                    details={"to": to, "subject": subject, "status_code": response.status_code, "message_id": msg_id},
                )
            else:
                return ConnectorResult(
                    success=False,
                    message=f"SendGrid returned unexpected status {response.status_code}: {response.body}",
                )

        except Exception as e:
            return ConnectorResult(
                success=False,
                message=f"SendGrid error: {e}",
            )


ConnectorRegistry.register(SendGridEmailConnector())
