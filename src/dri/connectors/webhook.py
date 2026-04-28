"""
Webhook connector — HTTP POST to any URL.

Handles action_type = "webhook" or any action where recipient is a URL.
Auto-detects the target platform (Slack, Discord, generic) from the URL
and formats the payload accordingly.

Supported platforms:
- Slack incoming webhooks  (hooks.slack.com)     → {"text": content}
- Discord webhooks         (discord.com/api/webhooks) → {"content": content, "username": ...}
- Make.com / Zapier / n8n  (any other URL)       → full action payload as JSON

Setup:
  No global config required — the webhook URL is the `recipient` field of the action.
  Agents must set recipient to the full webhook URL when using action_type="webhook".
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from dri.connectors.base import BaseConnector, ConnectorResult
from dri.connectors.registry import ConnectorRegistry


def _is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def _build_payload(action: dict) -> dict[str, Any]:
    """Build the JSON payload adapted to the target platform."""
    recipient: str = action.get("recipient", "")
    content: str = action.get("content", "")
    company: str = action.get("company", "DRI Agent")
    proposed_by: str = action.get("proposed_by", "Agent")

    sender_label = f"{company} — {proposed_by}"

    # Slack incoming webhook format
    if "hooks.slack.com" in recipient:
        return {
            "text": content,
            "username": sender_label,
            "icon_emoji": ":robot_face:",
        }

    # Discord webhook format
    if "discord.com/api/webhooks" in recipient:
        return {
            "content": content[:2000],  # Discord 2000-char limit
            "username": sender_label,
        }

    # Generic / Make.com / Zapier / n8n — send the full action context
    return {
        "text": content,
        "content": content,
        "message": content,
        "subject": action.get("subject", ""),
        "action_type": action.get("action_type", "webhook"),
        "recipient": recipient,
        "rationale": action.get("rationale", ""),
        "proposed_by": proposed_by,
        "company": company,
        "proposed_at": action.get("proposed_at", ""),
    }


class WebhookConnector(BaseConnector):
    """
    Executes any action whose recipient is an HTTP/HTTPS URL by POSTing to it.

    Handles:
    - action_type = "webhook" (always, if recipient is a URL)
    - action_type = "social_post" (if recipient looks like a webhook URL)
    - action_type = "outreach_message" (if recipient looks like a webhook URL)
    """

    def can_handle(self, action_type: str, action: dict) -> bool:
        if action_type == "webhook":
            return _is_url(action.get("recipient", ""))
        # For social_post / outreach routed through a webhook URL
        if action_type in ("social_post", "outreach_message"):
            return _is_url(action.get("recipient", ""))
        return False

    @property
    def is_configured(self) -> bool:
        # Always "configured" — the URL is provided per-action, not globally.
        return True

    @property
    def setup_hint(self) -> str:
        return "Set recipient to a webhook URL (Slack/Discord/Make.com/Zapier)."

    async def execute(self, action: dict) -> ConnectorResult:
        url = action.get("recipient", "")
        if not _is_url(url):
            return ConnectorResult(
                success=False,
                message=f"Recipient '{url}' is not a valid URL. Cannot send webhook.",
            )

        payload = _build_payload(action)

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()

            # Slack returns "ok", Discord returns 204, generic returns 200
            return ConnectorResult(
                success=True,
                message=f"Webhook delivered to {_platform_name(url)} (HTTP {response.status_code}).",
                details={"url": url, "status_code": response.status_code},
            )

        except httpx.HTTPStatusError as e:
            return ConnectorResult(
                success=False,
                message=f"Webhook failed — HTTP {e.response.status_code}: {e.response.text[:200]}",
            )
        except Exception as e:
            return ConnectorResult(
                success=False,
                message=f"Webhook error: {e}",
            )


def _platform_name(url: str) -> str:
    if "hooks.slack.com" in url:
        return "Slack"
    if "discord.com/api/webhooks" in url:
        return "Discord"
    if "hook.us.make.com" in url or "hook.eu.make.com" in url or "eu1.make.com" in url:
        return "Make.com"
    if "hooks.zapier.com" in url:
        return "Zapier"
    if "n8n" in url:
        return "n8n"
    return url.split("/")[2]  # domain only


ConnectorRegistry.register(WebhookConnector())
