"""
Live integration tests for connectors — make REAL network calls.

These tests are SKIPPED automatically when the required credentials are absent.
To run them, configure the relevant variables in your .env file.

Run only live tests:
    uv run pytest tests/integration/test_connectors_live.py -v

Each test is independent: a failure in one connector does not affect the others.

Required .env variables per connector:
  Slack Bot   : SLACK_BOT_TOKEN  +  SLACK_DEFAULT_CHANNEL (e.g. #general)
  Twilio SMS  : TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN + TWILIO_FROM_NUMBER
                + TEST_PHONE_NUMBER (recipient, set in .env or env var)
  SendGrid    : SENDGRID_API_KEY + SENDGRID_FROM_EMAIL
                + TEST_EMAIL_RECIPIENT (recipient, set in .env or env var)
  LinkedIn    : LINKEDIN_ACCESS_TOKEN
  SMTP        : SMTP_HOST + SMTP_USER + SMTP_PASSWORD
                + TEST_EMAIL_RECIPIENT
  Webhook     : TEST_WEBHOOK_URL (any URL that accepts POST, e.g. https://webhook.site/...)
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Charge le .env depuis la racine du projet dans os.environ
load_dotenv(Path(__file__).parent.parent.parent / ".env", override=True)


# ─── helpers ─────────────────────────────────────────────────────────────────

def _env(key: str) -> str:
    """Read directly from env (bypasses the lru_cache settings singleton)."""
    return os.environ.get(key, "")


def _skip_unless(*env_keys: str):
    """Skip the test if any of the required env vars are missing."""
    missing = [k for k in env_keys if not _env(k)]
    if missing:
        return pytest.mark.skip(reason=f"Missing env var(s): {', '.join(missing)}")
    return pytest.mark.skipif(False, reason="")


# ─── Webhook (no credentials — just a URL) ───────────────────────────────────

@pytest.mark.asyncio
@_skip_unless("TEST_WEBHOOK_URL")
async def test_live_webhook():
    """POST a test payload to TEST_WEBHOOK_URL."""
    from dri.connectors.webhook import WebhookConnector

    result = await WebhookConnector().execute({
        "action_type": "webhook",
        "recipient": _env("TEST_WEBHOOK_URL"),
        "content": "[DRI Live Test] Webhook connector works.",
        "company": "DRI Test",
        "proposed_by": "test_connectors_live.py",
    })

    print(f"\n  -> {result.message}")
    if not result.success and "429" in result.message:
        pytest.skip(f"Webhook rate-limited (HTTP 429): {result.message}")
    assert result.success, result.message


# ─── Slack Bot ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@_skip_unless("SLACK_BOT_TOKEN", "SLACK_DEFAULT_CHANNEL")
async def test_live_slack_bot():
    """Post a test message to SLACK_DEFAULT_CHANNEL."""
    from dri.config.settings import get_settings
    get_settings.cache_clear()

    from dri.connectors.slack_bot import SlackBotConnector

    result = await SlackBotConnector().execute({
        "action_type": "slack_message",
        "recipient": _env("SLACK_DEFAULT_CHANNEL"),
        "content": "[DRI Live Test] Slack Bot connector works. You can delete this message.",
        "company": "DRI Test",
        "proposed_by": "test_connectors_live.py",
    })

    print(f"\n  -> {result.message}")
    assert result.success, result.message


# ─── Twilio SMS ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@_skip_unless("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "TEST_PHONE_NUMBER")
async def test_live_twilio_sms():
    """Send a test SMS to TEST_PHONE_NUMBER."""
    from dri.config.settings import get_settings
    get_settings.cache_clear()

    from dri.connectors.twilio_sms import TwilioSMSConnector

    result = await TwilioSMSConnector().execute({
        "action_type": "sms",
        "recipient": _env("TEST_PHONE_NUMBER"),
        "content": "[DRI Live Test] Twilio SMS connector works.",
        "company": "DRI Test",
        "proposed_by": "test_connectors_live.py",
    })

    print(f"\n  -> {result.message}")
    assert result.success, result.message


# ─── SendGrid ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@_skip_unless("SENDGRID_API_KEY", "SENDGRID_FROM_EMAIL", "TEST_EMAIL_RECIPIENT")
async def test_live_sendgrid():
    """Send a test email via SendGrid to TEST_EMAIL_RECIPIENT."""
    from dri.config.settings import get_settings
    get_settings.cache_clear()

    from dri.connectors.sendgrid_email import SendGridEmailConnector

    result = await SendGridEmailConnector().execute({
        "action_type": "email",
        "recipient": _env("TEST_EMAIL_RECIPIENT"),
        "subject": "[DRI Live Test] SendGrid connector",
        "content": "This is a live test from the DRI connector suite. You can ignore this email.",
        "company": "DRI Test",
        "proposed_by": "test_connectors_live.py",
    })

    print(f"\n  -> {result.message}")
    assert result.success, result.message


# ─── SMTP ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@_skip_unless("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "TEST_EMAIL_RECIPIENT")
async def test_live_smtp():
    """Send a test email via SMTP to TEST_EMAIL_RECIPIENT."""
    from dri.config.settings import get_settings
    get_settings.cache_clear()

    from dri.connectors.email_smtp import EmailSMTPConnector

    result = await EmailSMTPConnector().execute({
        "action_type": "email",
        "recipient": _env("TEST_EMAIL_RECIPIENT"),
        "subject": "[DRI Live Test] SMTP connector",
        "content": "This is a live test from the DRI connector suite. You can ignore this email.",
        "company": "DRI Test",
        "proposed_by": "test_connectors_live.py",
    })

    print(f"\n  -> {result.message}")
    assert result.success, result.message


# ─── LinkedIn ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@_skip_unless("LINKEDIN_ACCESS_TOKEN")
async def test_live_linkedin_post():
    """Publish a test post on LinkedIn feed."""
    from dri.config.settings import get_settings
    get_settings.cache_clear()

    from dri.connectors.linkedin import LinkedInConnector

    result = await LinkedInConnector().execute({
        "action_type": "social_post",
        "recipient": "linkedin.com",
        "content": (
            "[DRI Live Test] Automated post from the DRI multi-agent system. "
            "Testing LinkedIn connector integration. Feel free to delete."
        ),
        "company": "DRI Test",
        "proposed_by": "test_connectors_live.py",
    })

    print(f"\n  -> {result.message}")
    assert result.success, result.message
