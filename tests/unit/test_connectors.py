"""
Unit tests for all connectors.

No real network calls — HTTP is mocked. Tests cover:
- can_handle routing logic (which connector claims which action)
- is_configured when credentials are absent
- Success and error paths with mocked HTTP responses
- SendGrid/SMTP fallback priority
- New action_type enum values (slack_message, sms)
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import dri.connectors  # noqa: F401 — trigger registration


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _unconfigured_settings(**overrides):
    """Return a minimal settings-like namespace with all connector keys empty."""
    base = dict(
        slack_bot_token="", slack_default_channel="",
        has_slack=False,
        twilio_account_sid="", twilio_auth_token="", twilio_from_number="",
        has_twilio=False,
        sendgrid_api_key="", sendgrid_from_email="", sendgrid_from_name="DRI",
        has_sendgrid=False,
        linkedin_access_token="", linkedin_person_urn="",
        has_linkedin=False,
        smtp_host="", smtp_user="", smtp_password="",
        has_email=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _httpx_response(status_code: int, json_body: dict | None = None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.text = text
    if status_code >= 400:
        from httpx import HTTPStatusError, Request, Response
        resp.raise_for_status.side_effect = HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=resp,
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


# ─── can_handle routing ───────────────────────────────────────────────────────

class TestCanHandle:
    def _connector(self, name: str):
        from dri.connectors.registry import ConnectorRegistry
        for c in ConnectorRegistry._connectors:
            if type(c).__name__ == name:
                return c
        raise KeyError(f"Connector {name} not registered")

    def test_webhook_handles_http_url(self):
        c = self._connector("WebhookConnector")
        assert c.can_handle("webhook", {"recipient": "https://hooks.example.com/abc"})

    def test_webhook_rejects_slack_channel(self):
        c = self._connector("WebhookConnector")
        assert not c.can_handle("webhook", {"recipient": "#general"})

    def test_slack_handles_slack_message(self):
        c = self._connector("SlackBotConnector")
        assert c.can_handle("slack_message", {"recipient": "#general"})

    def test_slack_handles_webhook_with_channel_name(self):
        c = self._connector("SlackBotConnector")
        assert c.can_handle("webhook", {"recipient": "#marketing"})

    def test_slack_handles_webhook_with_channel_id(self):
        c = self._connector("SlackBotConnector")
        assert c.can_handle("webhook", {"recipient": "C01234ABCDE"})

    def test_slack_handles_webhook_with_user_id(self):
        c = self._connector("SlackBotConnector")
        assert c.can_handle("webhook", {"recipient": "U98765ZZZZZ"})

    def test_slack_rejects_webhook_url(self):
        c = self._connector("SlackBotConnector")
        assert not c.can_handle("webhook", {"recipient": "https://hooks.slack.com/services/abc"})

    def test_twilio_handles_sms(self):
        c = self._connector("TwilioSMSConnector")
        assert c.can_handle("sms", {"recipient": "+33612345678"})

    def test_twilio_rejects_email(self):
        c = self._connector("TwilioSMSConnector")
        assert not c.can_handle("email", {"recipient": "user@example.com"})

    def test_linkedin_handles_social_post_with_linkedin_recipient(self):
        c = self._connector("LinkedInConnector")
        assert c.can_handle("social_post", {"recipient": "linkedin.com/company/myco"})

    def test_linkedin_rejects_social_post_without_linkedin_in_recipient(self):
        c = self._connector("LinkedInConnector")
        assert not c.can_handle("social_post", {"recipient": "https://hooks.slack.com/abc"})

    def test_linkedin_handles_linkedin_message(self):
        c = self._connector("LinkedInConnector")
        assert c.can_handle("linkedin_message", {"recipient": "John Doe"})

    def test_sendgrid_handles_email_when_configured(self):
        c = self._connector("SendGridEmailConnector")
        with patch("dri.connectors.sendgrid_email.settings") as s:
            s.has_sendgrid = True
            assert c.can_handle("email", {"recipient": "test@example.com"})

    def test_sendgrid_rejects_email_when_unconfigured(self):
        c = self._connector("SendGridEmailConnector")
        with patch("dri.connectors.sendgrid_email.settings") as s:
            s.has_sendgrid = False
            assert not c.can_handle("email", {"recipient": "test@example.com"})

    def test_smtp_handles_email(self):
        c = self._connector("EmailSMTPConnector")
        assert c.can_handle("email", {"recipient": "test@example.com"})


# ─── is_configured ────────────────────────────────────────────────────────────

class TestIsConfigured:
    def test_slack_unconfigured(self):
        from dri.connectors.slack_bot import SlackBotConnector
        with patch("dri.connectors.slack_bot.settings", _unconfigured_settings()):
            assert not SlackBotConnector().is_configured

    def test_slack_configured(self):
        from dri.connectors.slack_bot import SlackBotConnector
        with patch("dri.connectors.slack_bot.settings", _unconfigured_settings(slack_bot_token="xoxb-test", has_slack=True)):
            assert SlackBotConnector().is_configured

    def test_twilio_unconfigured(self):
        from dri.connectors.twilio_sms import TwilioSMSConnector
        with patch("dri.connectors.twilio_sms.settings", _unconfigured_settings()):
            assert not TwilioSMSConnector().is_configured

    def test_sendgrid_unconfigured(self):
        from dri.connectors.sendgrid_email import SendGridEmailConnector
        with patch("dri.connectors.sendgrid_email.settings", _unconfigured_settings()):
            assert not SendGridEmailConnector().is_configured

    def test_linkedin_unconfigured(self):
        from dri.connectors.linkedin import LinkedInConnector
        with patch("dri.connectors.linkedin.settings", _unconfigured_settings()):
            assert not LinkedInConnector().is_configured


# ─── Webhook connector ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_webhook_send_success():
    from dri.connectors.webhook import WebhookConnector
    mock_resp = _httpx_response(200)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("dri.connectors.webhook.httpx.AsyncClient", return_value=mock_client):
        result = await WebhookConnector().execute({
            "action_type": "webhook",
            "recipient": "https://hooks.example.com/test",
            "content": "Hello from DRI",
        })

    assert result.success
    assert "200" in result.message


@pytest.mark.asyncio
async def test_webhook_send_http_error():
    from dri.connectors.webhook import WebhookConnector
    mock_resp = _httpx_response(500, text="Internal Server Error")

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("dri.connectors.webhook.httpx.AsyncClient", return_value=mock_client):
        result = await WebhookConnector().execute({
            "action_type": "webhook",
            "recipient": "https://hooks.example.com/fail",
            "content": "This will fail",
        })

    assert not result.success


@pytest.mark.asyncio
async def test_webhook_invalid_recipient():
    from dri.connectors.webhook import WebhookConnector
    result = await WebhookConnector().execute({
        "action_type": "webhook",
        "recipient": "not-a-url",
        "content": "irrelevant",
    })
    assert not result.success
    assert "not a valid URL" in result.message


# ─── Slack Bot connector ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slack_send_success():
    from dri.connectors.slack_bot import SlackBotConnector

    configured = _unconfigured_settings(slack_bot_token="xoxb-fake", has_slack=True)
    mock_resp = _httpx_response(200, {"ok": True, "ts": "1234567890.123456"})

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("dri.connectors.slack_bot.settings", configured), \
         patch("dri.connectors.slack_bot.httpx.AsyncClient", return_value=mock_client):
        result = await SlackBotConnector().execute({
            "action_type": "slack_message",
            "recipient": "#general",
            "content": "Test message",
        })

    assert result.success
    assert result.external_id == "1234567890.123456"


@pytest.mark.asyncio
async def test_slack_api_error_response():
    from dri.connectors.slack_bot import SlackBotConnector

    configured = _unconfigured_settings(slack_bot_token="xoxb-fake", has_slack=True)
    mock_resp = _httpx_response(200, {"ok": False, "error": "channel_not_found"})

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("dri.connectors.slack_bot.settings", configured), \
         patch("dri.connectors.slack_bot.httpx.AsyncClient", return_value=mock_client):
        result = await SlackBotConnector().execute({
            "action_type": "slack_message",
            "recipient": "#nonexistent",
            "content": "Test",
        })

    assert not result.success
    assert "channel_not_found" in result.message


@pytest.mark.asyncio
async def test_slack_no_recipient_uses_default():
    from dri.connectors.slack_bot import SlackBotConnector

    configured = _unconfigured_settings(
        slack_bot_token="xoxb-fake", has_slack=True, slack_default_channel="#fallback"
    )
    mock_resp = _httpx_response(200, {"ok": True, "ts": "111.222"})

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("dri.connectors.slack_bot.settings", configured), \
         patch("dri.connectors.slack_bot.httpx.AsyncClient", return_value=mock_client):
        result = await SlackBotConnector().execute({
            "action_type": "slack_message",
            "recipient": "",   # empty — should fall back to default
            "content": "Test",
        })

    assert result.success
    call_payload = mock_client.post.call_args.kwargs["json"]
    assert call_payload["channel"] == "#fallback"


@pytest.mark.asyncio
async def test_slack_unconfigured_returns_error():
    from dri.connectors.slack_bot import SlackBotConnector
    with patch("dri.connectors.slack_bot.settings", _unconfigured_settings()):
        result = await SlackBotConnector().execute({"recipient": "#general", "content": "x"})
    assert not result.success
    assert "not configured" in result.message


# ─── Twilio SMS connector ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_twilio_unconfigured_returns_error():
    from dri.connectors.twilio_sms import TwilioSMSConnector
    with patch("dri.connectors.twilio_sms.settings", _unconfigured_settings()):
        result = await TwilioSMSConnector().execute({"recipient": "+33600000000", "content": "test"})
    assert not result.success
    assert "not configured" in result.message


@pytest.mark.asyncio
async def test_twilio_send_success():
    from dri.connectors.base import ConnectorResult
    from dri.connectors.twilio_sms import TwilioSMSConnector

    configured = _unconfigured_settings(
        twilio_account_sid="ACfake", twilio_auth_token="fake", twilio_from_number="+15550000000",
        has_twilio=True,
    )
    mock_result = ConnectorResult(
        success=True,
        message="SMS sent to +33600000000 (SID=SM1234567890abcdef, status=queued).",
        external_id="SM1234567890abcdef",
    )

    # Patch _send_sync only — asyncio.to_thread will call it normally in the thread pool.
    with patch("dri.connectors.twilio_sms.settings", configured):
        connector = TwilioSMSConnector()
        with patch.object(connector, "_send_sync", return_value=mock_result):
            result = await connector.execute({"recipient": "+33600000000", "content": "Hello!"})

    assert result.success
    assert "SM1234567890abcdef" in result.message


# ─── SendGrid connector ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sendgrid_unconfigured_returns_error():
    from dri.connectors.sendgrid_email import SendGridEmailConnector
    with patch("dri.connectors.sendgrid_email.settings", _unconfigured_settings()):
        result = await SendGridEmailConnector().execute({"recipient": "x@x.com", "content": "test"})
    assert not result.success
    assert "not configured" in result.message


@pytest.mark.asyncio
async def test_sendgrid_send_success():
    from dri.connectors.base import ConnectorResult
    from dri.connectors.sendgrid_email import SendGridEmailConnector

    configured = _unconfigured_settings(
        sendgrid_api_key="SG.fake", sendgrid_from_email="agent@example.com",
        sendgrid_from_name="DRI Agent", has_sendgrid=True,
    )

    mock_result = ConnectorResult(success=True, message="Email sent to test@example.com via SendGrid (status=202).", external_id="msg-001")

    with patch("dri.connectors.sendgrid_email.settings", configured):
        connector = SendGridEmailConnector()
        with patch.object(connector, "_send_sync", return_value=mock_result):
            result = await connector.execute({
                "recipient": "test@example.com",
                "subject": "Hello",
                "content": "Test email body.",
            })

    assert result.success
    assert "SendGrid" in result.message


# ─── LinkedIn connector ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_linkedin_message_returns_unsupported():
    from dri.connectors.linkedin import LinkedInConnector
    configured = _unconfigured_settings(linkedin_access_token="fake-token", has_linkedin=True)
    with patch("dri.connectors.linkedin.settings", configured):
        result = await LinkedInConnector().execute({
            "action_type": "linkedin_message",
            "recipient": "John Doe",
            "content": "Hi!",
        })
    assert not result.success
    assert "Partner" in result.message


@pytest.mark.asyncio
async def test_linkedin_post_success():
    from dri.connectors.linkedin import LinkedInConnector

    configured = _unconfigured_settings(
        linkedin_access_token="fake-token", linkedin_person_urn="urn:li:person:ABC123",
        has_linkedin=True,
    )

    mock_resp = _httpx_response(201)
    mock_resp.headers = {"x-restli-id": "urn:li:ugcPost:99999"}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("dri.connectors.linkedin.settings", configured), \
         patch("dri.connectors.linkedin.httpx.AsyncClient", return_value=mock_client):
        result = await LinkedInConnector().execute({
            "action_type": "social_post",
            "recipient": "linkedin.com/company/myco",
            "content": "Exciting news from our AI company!",
        })

    assert result.success
    assert "urn:li:ugcPost:99999" in result.message


@pytest.mark.asyncio
async def test_linkedin_expired_token():
    from dri.connectors.linkedin import LinkedInConnector

    configured = _unconfigured_settings(
        linkedin_access_token="expired-token", linkedin_person_urn="urn:li:person:ABC123",
        has_linkedin=True,
    )

    mock_resp = _httpx_response(401)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("dri.connectors.linkedin.settings", configured), \
         patch("dri.connectors.linkedin.httpx.AsyncClient", return_value=mock_client):
        result = await LinkedInConnector().execute({
            "action_type": "social_post",
            "recipient": "linkedin.com",
            "content": "Post content",
        })

    assert not result.success
    assert "expired" in result.message.lower() or "401" in result.message


# ─── propose_external_action — new types ─────────────────────────────────────

@pytest.mark.asyncio
async def test_propose_slack_message_type(tmp_path):
    from dri.tools.base import ToolRegistry
    tool = ToolRegistry.get("propose_external_action")
    result = await tool.execute({
        "_workspace_root": str(tmp_path),
        "_agent_title": "Marketing Manager",
        "_company_name": "TestCo",
        "action_type": "slack_message",
        "recipient": "#general",
        "content": "Team update: milestone reached!",
        "rationale": "Keep the team informed.",
    })
    assert result.success
    assert isinstance(result.data["action_id"], str)  # UUID string


@pytest.mark.asyncio
async def test_propose_sms_type(tmp_path):
    from dri.tools.base import ToolRegistry
    tool = ToolRegistry.get("propose_external_action")
    result = await tool.execute({
        "_workspace_root": str(tmp_path),
        "_agent_title": "Sales Agent",
        "_company_name": "TestCo",
        "action_type": "sms",
        "recipient": "+33612345678",
        "content": "Your order is confirmed!",
        "rationale": "Order confirmation SMS.",
    })
    assert result.success
    assert isinstance(result.data["action_id"], str)  # UUID string


@pytest.mark.asyncio
async def test_propose_invalid_type_rejected(tmp_path):
    from dri.tools.base import ToolRegistry
    tool = ToolRegistry.get("propose_external_action")
    result = await tool.execute({
        "_workspace_root": str(tmp_path),
        "_agent_title": "Agent",
        "_company_name": "TestCo",
        "action_type": "telegram_message",   # not in enum
        "recipient": "@someuser",
        "content": "Hello",
        "rationale": "Test",
    })
    assert not result.success
    assert "Invalid action_type" in result.error


# ─── GitHub connector ─────────────────────────────────────────────────────────

class TestGitHubCanHandle:
    def _connector(self):
        from dri.connectors.github import GitHubConnector
        return GitHubConnector()

    def test_handles_github_push(self):
        assert self._connector().can_handle("github_push", {})

    def test_handles_github_create_pr(self):
        assert self._connector().can_handle("github_create_pr", {})

    def test_handles_github_create_repo(self):
        assert self._connector().can_handle("github_create_repo", {})

    def test_rejects_email(self):
        assert not self._connector().can_handle("email", {})

    def test_rejects_webhook(self):
        assert not self._connector().can_handle("webhook", {})


class TestGitHubIsConfigured:
    def test_unconfigured_when_no_token(self):
        from dri.connectors.github import GitHubConnector
        from types import SimpleNamespace
        with patch("dri.connectors.github.settings", SimpleNamespace(has_github=False, github_token="")):
            assert not GitHubConnector().is_configured

    def test_configured_when_token_present(self):
        from dri.connectors.github import GitHubConnector
        from types import SimpleNamespace
        with patch("dri.connectors.github.settings", SimpleNamespace(has_github=True, github_token="ghp_test")):
            assert GitHubConnector().is_configured


@pytest.mark.asyncio
async def test_github_unconfigured_returns_error():
    from dri.connectors.github import GitHubConnector
    from types import SimpleNamespace
    with patch("dri.connectors.github.settings", SimpleNamespace(has_github=False, github_token="")):
        result = await GitHubConnector().execute({"action_type": "github_push", "recipient": "owner/repo"})
    assert not result.success
    assert "not configured" in result.message


@pytest.mark.asyncio
async def test_github_push_missing_repo():
    from dri.connectors.github import GitHubConnector
    from types import SimpleNamespace
    with patch("dri.connectors.github.settings", SimpleNamespace(has_github=True, github_token="tok")):
        result = await GitHubConnector().execute({
            "action_type": "github_push",
            "recipient": "",   # missing
            "subject": "main:src/app.py",
            "content": "print('hello')",
            "rationale": "add file",
        })
    assert not result.success
    assert "owner/repo" in result.message


@pytest.mark.asyncio
async def test_github_push_new_file_success():
    from dri.connectors.github import GitHubConnector
    from types import SimpleNamespace

    configured = SimpleNamespace(has_github=True, github_token="ghp_fake")
    get_resp = _httpx_response(404)  # file doesn't exist yet
    put_resp = _httpx_response(201)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    # GET check returns 404, then PUT creates file
    mock_client.get = AsyncMock(return_value=get_resp)
    mock_client.put = AsyncMock(return_value=put_resp)

    with patch("dri.connectors.github.settings", configured), \
         patch("dri.connectors.github.httpx.AsyncClient", return_value=mock_client):
        result = await GitHubConnector().execute({
            "action_type": "github_push",
            "recipient": "myorg/myrepo",
            "subject": "main:src/app.py",
            "content": "print('hello')",
            "rationale": "add app.py",
        })

    assert result.success
    assert "Created" in result.message
    assert "src/app.py" in result.message


@pytest.mark.asyncio
async def test_github_push_update_existing_file():
    from dri.connectors.github import GitHubConnector
    from types import SimpleNamespace

    configured = SimpleNamespace(has_github=True, github_token="ghp_fake")
    get_resp = _httpx_response(200, {"sha": "abc123def456"})
    put_resp = _httpx_response(200)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=get_resp)
    mock_client.put = AsyncMock(return_value=put_resp)

    with patch("dri.connectors.github.settings", configured), \
         patch("dri.connectors.github.httpx.AsyncClient", return_value=mock_client):
        result = await GitHubConnector().execute({
            "action_type": "github_push",
            "recipient": "myorg/myrepo",
            "subject": "main:src/app.py",
            "content": "print('updated')",
            "rationale": "update app.py",
        })

    assert result.success
    assert "Updated" in result.message
    # SHA should have been passed to the PUT call
    put_payload = mock_client.put.call_args.kwargs["json"]
    assert put_payload["sha"] == "abc123def456"


@pytest.mark.asyncio
async def test_github_create_pr_success_with_json_content():
    from dri.connectors.github import GitHubConnector
    from types import SimpleNamespace
    import json

    configured = SimpleNamespace(has_github=True, github_token="ghp_fake")
    pr_body = json.dumps({"head": "feature-x", "base": "main", "body": "Adds feature X"})
    resp = _httpx_response(201, {"number": 42, "html_url": "https://github.com/myorg/myrepo/pull/42"})

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=resp)

    with patch("dri.connectors.github.settings", configured), \
         patch("dri.connectors.github.httpx.AsyncClient", return_value=mock_client):
        result = await GitHubConnector().execute({
            "action_type": "github_create_pr",
            "recipient": "myorg/myrepo",
            "subject": "Add feature X",
            "content": pr_body,
            "rationale": "new feature",
        })

    assert result.success
    assert "42" in result.message
    assert result.external_id == "42"


@pytest.mark.asyncio
async def test_github_create_pr_same_head_base_rejected():
    from dri.connectors.github import GitHubConnector
    from types import SimpleNamespace
    import json

    configured = SimpleNamespace(has_github=True, github_token="ghp_fake")
    pr_body = json.dumps({"head": "main", "base": "main", "body": "oops"})

    with patch("dri.connectors.github.settings", configured):
        result = await GitHubConnector().execute({
            "action_type": "github_create_pr",
            "recipient": "myorg/myrepo",
            "subject": "Bad PR",
            "content": pr_body,
            "rationale": "test",
        })

    assert not result.success
    assert "head and base" in result.message


@pytest.mark.asyncio
async def test_github_create_repo_success():
    from dri.connectors.github import GitHubConnector
    from types import SimpleNamespace

    configured = SimpleNamespace(has_github=True, github_token="ghp_fake")
    resp = _httpx_response(201, {
        "full_name": "myorg/new-repo",
        "html_url": "https://github.com/myorg/new-repo",
    })

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=resp)

    with patch("dri.connectors.github.settings", configured), \
         patch("dri.connectors.github.httpx.AsyncClient", return_value=mock_client):
        result = await GitHubConnector().execute({
            "action_type": "github_create_repo",
            "recipient": "myorg",
            "subject": "new-repo",
            "content": "A brand new repository",
            "rationale": "start fresh",
        })

    assert result.success
    assert "myorg/new-repo" in result.message
    # Should use org endpoint when recipient is set
    call_url = mock_client.post.call_args.args[0]
    assert "orgs/myorg" in call_url


@pytest.mark.asyncio
async def test_github_create_repo_personal_account():
    from dri.connectors.github import GitHubConnector
    from types import SimpleNamespace

    configured = SimpleNamespace(has_github=True, github_token="ghp_fake")
    resp = _httpx_response(201, {
        "full_name": "ethan/my-repo",
        "html_url": "https://github.com/ethan/my-repo",
    })

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=resp)

    with patch("dri.connectors.github.settings", configured), \
         patch("dri.connectors.github.httpx.AsyncClient", return_value=mock_client):
        result = await GitHubConnector().execute({
            "action_type": "github_create_repo",
            "recipient": "",   # personal account
            "subject": "my-repo",
            "content": "Personal repo",
            "rationale": "personal project",
        })

    assert result.success
    # Should use /user/repos endpoint
    call_url = mock_client.post.call_args.args[0]
    assert "/user/repos" in call_url


@pytest.mark.asyncio
async def test_github_propose_push_action_type_accepted(tmp_path):
    """propose_external_action accepts github_push as a valid action_type."""
    from dri.tools.base import ToolRegistry
    tool = ToolRegistry.get("propose_external_action")
    result = await tool.execute({
        "_workspace_root": str(tmp_path),
        "_agent_title": "Backend Developer",
        "_company_name": "TestCo",
        "action_type": "github_push",
        "recipient": "myorg/myrepo",
        "subject": "main:src/app.py",
        "content": "print('hello world')",
        "rationale": "Push initial app file to repo",
    })
    assert result.success


@pytest.mark.asyncio
async def test_github_propose_create_repo_type_accepted(tmp_path):
    """propose_external_action accepts github_create_repo as a valid action_type."""
    from dri.tools.base import ToolRegistry
    tool = ToolRegistry.get("propose_external_action")
    result = await tool.execute({
        "_workspace_root": str(tmp_path),
        "_agent_title": "CTO",
        "_company_name": "TestCo",
        "action_type": "github_create_repo",
        "recipient": "myorg",
        "subject": "new-project",
        "content": "A new project repository",
        "rationale": "Start new GitHub project",
    })
    assert result.success
