"""
Slack Bot Token connector — posts messages via the Slack Web API.

More powerful than incoming webhooks: can target any channel by name or ID,
post to DMs (user ID), and is authenticated by your app's bot token.

Handles:
- action_type = "slack_message"  (new, dedicated type — preferred)
- action_type = "webhook" + recipient is a channel name (#general),
  a channel ID (C...), or a user ID (U...) — NOT a webhook URL

Setup (.env):
  SLACK_BOT_TOKEN=xoxb-...          # required
  SLACK_DEFAULT_CHANNEL=#general    # optional fallback when recipient is empty

Slack app setup:
  1. Go to https://api.slack.com/apps → Create New App → From scratch
  2. Add OAuth scope: chat:write  (Bot Token Scopes)
  3. Install app to your workspace → copy the Bot User OAuth Token (xoxb-...)
  4. Invite the bot to your channel: /invite @your-bot-name
"""
from __future__ import annotations

import httpx

from dri.config.settings import settings
from dri.connectors.base import BaseConnector, ConnectorResult
from dri.connectors.registry import ConnectorRegistry

_SLACK_API = "https://slack.com/api/chat.postMessage"


def _looks_like_slack_target(recipient: str) -> bool:
    """True when recipient is a channel name, channel ID, or user ID — not an HTTP URL."""
    if recipient.startswith("http://") or recipient.startswith("https://"):
        return False
    return (
        recipient.startswith("#")
        or recipient.startswith("C")   # Slack channel IDs start with C
        or recipient.startswith("U")   # Slack user IDs start with U
    )


class SlackBotConnector(BaseConnector):
    """
    Posts messages to Slack via the Web API using a Bot Token.

    The `recipient` field should be a channel name (#general), channel ID (C12345),
    or user ID (U12345). Falls back to SLACK_DEFAULT_CHANNEL if recipient is empty.
    """

    def can_handle(self, action_type: str, action: dict) -> bool:
        if action_type == "slack_message":
            return True
        if action_type == "webhook":
            recipient = action.get("recipient", "")
            return _looks_like_slack_target(recipient)
        return False

    @property
    def is_configured(self) -> bool:
        return bool(settings.slack_bot_token)

    @property
    def setup_hint(self) -> str:
        return (
            "Set SLACK_BOT_TOKEN=xoxb-... in .env. "
            "Create a Slack app at https://api.slack.com/apps, add the chat:write scope, "
            "install it to your workspace, and invite the bot to the target channel with /invite."
        )

    async def execute(self, action: dict) -> ConnectorResult:
        if not self.is_configured:
            return ConnectorResult(
                success=False,
                message=f"Slack connector not configured. {self.setup_hint}",
            )

        recipient = action.get("recipient", "").strip() or settings.slack_default_channel
        if not recipient:
            return ConnectorResult(
                success=False,
                message=(
                    "No Slack recipient provided and SLACK_DEFAULT_CHANNEL is not set. "
                    "Set recipient to a channel name (#general) or set SLACK_DEFAULT_CHANNEL in .env."
                ),
            )

        content = action.get("content", "")
        company = action.get("company", "DRI Agent")
        proposed_by = action.get("proposed_by", "Agent")
        sender_label = f"{company} — {proposed_by}"

        payload = {
            "channel": recipient,
            "text": content,
            "username": sender_label,
            "icon_emoji": ":robot_face:",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    _SLACK_API,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {settings.slack_bot_token}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                data = response.json()

            if not data.get("ok"):
                error = data.get("error", "unknown_error")
                return ConnectorResult(
                    success=False,
                    message=f"Slack API error: {error}. Check bot permissions and channel access.",
                )

            ts = data.get("ts", "")
            return ConnectorResult(
                success=True,
                message=f"Message posted to Slack {recipient} (ts={ts}).",
                external_id=ts,
                details={"channel": recipient, "ts": ts},
            )

        except httpx.HTTPStatusError as e:
            return ConnectorResult(
                success=False,
                message=f"Slack request failed — HTTP {e.response.status_code}: {e.response.text[:200]}",
            )
        except Exception as e:
            return ConnectorResult(
                success=False,
                message=f"Slack connector error: {e}",
            )


ConnectorRegistry.register(SlackBotConnector())
