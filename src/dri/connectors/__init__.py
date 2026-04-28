# Import connectors to trigger self-registration into ConnectorRegistry.
# Order matters: more specific connectors should be registered first.
import dri.connectors.sendgrid_email  # noqa: F401  — takes priority over SMTP when configured
import dri.connectors.email_smtp      # noqa: F401  — SMTP fallback when SendGrid not configured
import dri.connectors.twilio_sms      # noqa: F401
import dri.connectors.linkedin        # noqa: F401  — before webhook (social_post + linkedin_message)
import dri.connectors.slack_bot       # noqa: F401  — Slack Bot API (before webhook, more specific)
import dri.connectors.webhook         # noqa: F401

from dri.connectors.base import BaseConnector, ConnectorResult
from dri.connectors.registry import ConnectorRegistry

__all__ = ["BaseConnector", "ConnectorResult", "ConnectorRegistry"]
