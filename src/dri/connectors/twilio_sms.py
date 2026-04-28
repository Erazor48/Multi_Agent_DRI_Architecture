"""
Twilio SMS connector — sends real SMS messages via the Twilio REST API.

Handles action_type = "sms".
The `recipient` field must be a phone number in E.164 format (+12125551234).
The `content` field is the SMS body text.

Setup (.env):
  TWILIO_ACCOUNT_SID=AC...
  TWILIO_AUTH_TOKEN=...
  TWILIO_FROM_NUMBER=+12125551234   # your Twilio number, E.164 format

Twilio quick-start:
  1. Sign up at https://www.twilio.com (free trial available)
  2. Get a phone number from the Console
  3. Copy your Account SID and Auth Token from the Console Dashboard
  4. Add the recipient number to Verified Caller IDs if on a trial account
"""
from __future__ import annotations

import asyncio

from dri.config.settings import settings
from dri.connectors.base import BaseConnector, ConnectorResult
from dri.connectors.registry import ConnectorRegistry


class TwilioSMSConnector(BaseConnector):
    """
    Sends SMS messages via Twilio for action_type = "sms".
    The `recipient` field is the destination phone number in E.164 format (+12125551234).
    The `content` field is the SMS body (max 1600 characters; longer messages are split).
    """

    def can_handle(self, action_type: str, action: dict) -> bool:
        return action_type == "sms"

    @property
    def is_configured(self) -> bool:
        return settings.has_twilio

    @property
    def setup_hint(self) -> str:
        return (
            "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER in .env. "
            "Get your credentials at https://www.twilio.com/console. "
            "TWILIO_FROM_NUMBER must be a Twilio number in E.164 format (+12125551234)."
        )

    async def execute(self, action: dict) -> ConnectorResult:
        if not self.is_configured:
            return ConnectorResult(
                success=False,
                message=f"Twilio SMS connector not configured. {self.setup_hint}",
            )

        recipient = action.get("recipient", "").strip()
        if not recipient:
            return ConnectorResult(success=False, message="No recipient phone number provided.")

        content = action.get("content", "").strip()
        if not content:
            return ConnectorResult(success=False, message="No SMS content provided.")

        try:
            result = await asyncio.to_thread(self._send_sync, recipient, content)
            return result
        except Exception as e:
            return ConnectorResult(success=False, message=f"Twilio SMS failed: {e}")

    def _send_sync(self, to: str, body: str) -> ConnectorResult:
        try:
            from twilio.rest import Client  # type: ignore[import-untyped]
            from twilio.base.exceptions import TwilioRestException  # type: ignore[import-untyped]
        except ImportError:
            return ConnectorResult(
                success=False,
                message="twilio package not installed. Run: uv sync",
            )

        try:
            client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
            message = client.messages.create(
                to=to,
                from_=settings.twilio_from_number,
                body=body,
            )
            return ConnectorResult(
                success=True,
                message=f"SMS sent to {to} (SID={message.sid}, status={message.status}).",
                external_id=message.sid,
                details={"to": to, "from": settings.twilio_from_number, "sid": message.sid, "status": message.status},
            )
        except TwilioRestException as e:
            return ConnectorResult(
                success=False,
                message=f"Twilio error {e.code}: {e.msg}. Check your credentials and recipient number.",
            )


ConnectorRegistry.register(TwilioSMSConnector())
