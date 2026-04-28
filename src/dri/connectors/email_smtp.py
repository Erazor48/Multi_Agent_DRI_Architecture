"""
Email connector — sends real emails via SMTP.

Uses Python stdlib only (smtplib + email.mime). No extra dependencies.
Supports STARTTLS (port 587, default for Gmail/Outlook) and SSL (port 465).

Setup (.env):
  SMTP_HOST=smtp.gmail.com
  SMTP_PORT=587
  SMTP_USER=you@gmail.com
  SMTP_PASSWORD=your_app_password   # Gmail: Settings → Security → App passwords
  SMTP_FROM=you@gmail.com           # Optional — defaults to SMTP_USER

Gmail quick-start:
  1. Enable 2-Factor Authentication on your Google account
  2. Go to myaccount.google.com → Security → App passwords
  3. Create an app password for "Mail" and paste it as SMTP_PASSWORD

Outlook/Hotmail:
  SMTP_HOST=smtp.office365.com, SMTP_PORT=587

Custom SMTP:
  Set SMTP_HOST/PORT/USER/PASSWORD to your provider's values.
"""
from __future__ import annotations

import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dri.config.settings import settings
from dri.connectors.base import BaseConnector, ConnectorResult
from dri.connectors.registry import ConnectorRegistry


class EmailSMTPConnector(BaseConnector):
    """
    Sends emails via SMTP for action_type = "email".
    The `recipient` field is the destination email address.
    The `subject` field becomes the email subject line.
    The `content` field is the email body (plain text).
    """

    def can_handle(self, action_type: str, action: dict) -> bool:
        return action_type == "email"

    @property
    def is_configured(self) -> bool:
        return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)

    @property
    def setup_hint(self) -> str:
        return (
            "Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD in .env. "
            "For Gmail: use an App Password (myaccount.google.com → Security → App passwords)."
        )

    async def execute(self, action: dict) -> ConnectorResult:
        if not self.is_configured:
            return ConnectorResult(
                success=False,
                message=f"Email connector not configured. {self.setup_hint}",
            )

        recipient = action.get("recipient", "").strip()
        if not recipient:
            return ConnectorResult(success=False, message="No recipient email address provided.")

        subject = (
            action.get("subject", "").strip()
            or f"Message from {action.get('company', 'DRI')} — {action.get('proposed_by', 'Agent')}"
        )
        content = action.get("content", "")
        sender = settings.smtp_from_address

        try:
            result = await asyncio.to_thread(
                self._send_sync, sender, recipient, subject, content
            )
            return result
        except Exception as e:
            return ConnectorResult(success=False, message=f"Email send failed: {e}")

    def _send_sync(
        self, sender: str, recipient: str, subject: str, content: str
    ) -> ConnectorResult:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = recipient

        msg.attach(MIMEText(content, "plain", "utf-8"))

        try:
            if settings.smtp_port == 465:
                # SSL — wrap the connection from the start
                import ssl
                ctx = ssl.create_default_context()
                with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=ctx) as server:
                    server.login(settings.smtp_user, settings.smtp_password)
                    server.sendmail(sender, [recipient], msg.as_string())
            else:
                # STARTTLS (587) or plain (25)
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                    server.ehlo()
                    if settings.smtp_port != 25:
                        server.starttls()
                        server.ehlo()
                    server.login(settings.smtp_user, settings.smtp_password)
                    server.sendmail(sender, [recipient], msg.as_string())

            return ConnectorResult(
                success=True,
                message=f"Email sent to {recipient} via {settings.smtp_host}.",
                details={"from": sender, "to": recipient, "subject": subject},
            )

        except smtplib.SMTPAuthenticationError:
            return ConnectorResult(
                success=False,
                message=(
                    "SMTP authentication failed. "
                    "Check SMTP_USER and SMTP_PASSWORD. "
                    "For Gmail, use an App Password, not your account password."
                ),
            )
        except smtplib.SMTPException as e:
            return ConnectorResult(success=False, message=f"SMTP error: {e}")


ConnectorRegistry.register(EmailSMTPConnector())
