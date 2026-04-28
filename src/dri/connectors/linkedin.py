"""
LinkedIn connector — posts to LinkedIn via the REST API.

Handles:
- action_type = "social_post"  + "linkedin" in recipient → post to your LinkedIn feed
- action_type = "linkedin_message"               → returns a clear error (see note)

Note on linkedin_message:
  LinkedIn's direct messaging API (Messaging API v2) requires LinkedIn Partner Program
  access, which is not available through a standard developer app. Attempting to use
  it results in a 403 PERMISSION_DENIED error. Use action_type="social_post" and
  mention the person's name in the content instead.

Setup (.env):
  LINKEDIN_ACCESS_TOKEN=...       # required — OAuth 2.0 access token (valid 60 days)
  LINKEDIN_PERSON_URN=            # optional — auto-fetched from /v2/userinfo if empty

Getting your access token (one-time, no server required):
  1. Create a LinkedIn Developer App: https://www.linkedin.com/developers/apps
     Add products: "Share on LinkedIn" + "Sign In with LinkedIn using OpenID Connect"
     Required scopes: openid, profile, w_member_social
  2. In your app → Auth tab → OAuth 2.0 tools → generate a token for your own account.
  3. Paste it as LINKEDIN_ACCESS_TOKEN. Refresh every 60 days (LinkedIn does not
     provide refresh tokens for standard apps — re-generate manually from the portal).

No extra dependencies — uses httpx (already a project dependency).
"""
from __future__ import annotations

import httpx

from dri.config.settings import settings
from dri.connectors.base import BaseConnector, ConnectorResult
from dri.connectors.registry import ConnectorRegistry

_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
_UGC_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.linkedin_access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }


class LinkedInConnector(BaseConnector):
    """
    Posts to LinkedIn for action_type = "social_post" when "linkedin" is in recipient.
    Returns a clear unsupported message for action_type = "linkedin_message".
    """

    def can_handle(self, action_type: str, action: dict) -> bool:
        if action_type == "linkedin_message":
            return True
        if action_type == "social_post":
            recipient = action.get("recipient", "").lower()
            return "linkedin" in recipient
        return False

    @property
    def is_configured(self) -> bool:
        return settings.has_linkedin

    @property
    def setup_hint(self) -> str:
        return (
            "Set LINKEDIN_ACCESS_TOKEN in .env. "
            "Generate a token via your LinkedIn Developer App → Auth tab → OAuth 2.0 tools. "
            "Required scopes: openid, profile, w_member_social. Token is valid for 60 days."
        )

    async def execute(self, action: dict) -> ConnectorResult:
        if not self.is_configured:
            return ConnectorResult(
                success=False,
                message=f"LinkedIn connector not configured. {self.setup_hint}",
            )

        action_type = action.get("action_type", "")

        if action_type == "linkedin_message":
            return ConnectorResult(
                success=False,
                message=(
                    "LinkedIn direct messaging requires LinkedIn Partner Program access, "
                    "which is not available through a standard developer app. "
                    "Use action_type='social_post' with the person's name in the content instead."
                ),
            )

        return await self._post_to_feed(action)

    async def _post_to_feed(self, action: dict) -> ConnectorResult:
        content = action.get("content", "").strip()
        if not content:
            return ConnectorResult(success=False, message="No post content provided.")

        try:
            person_urn = await self._resolve_person_urn()
        except Exception as e:
            return ConnectorResult(
                success=False,
                message=f"Failed to resolve LinkedIn person URN: {e}. "
                        "Set LINKEDIN_PERSON_URN in .env to skip auto-fetch.",
            )

        payload = {
            "author": person_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": content},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            },
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    _UGC_POSTS_URL,
                    json=payload,
                    headers=_auth_headers(),
                )
                response.raise_for_status()

            post_id = response.headers.get("x-restli-id", "")
            return ConnectorResult(
                success=True,
                message=f"LinkedIn post published (id={post_id}).",
                external_id=post_id,
                details={"author": person_urn, "post_id": post_id},
            )

        except httpx.HTTPStatusError as e:
            body = e.response.text[:300]
            if e.response.status_code == 401:
                return ConnectorResult(
                    success=False,
                    message=(
                        "LinkedIn token expired or invalid (HTTP 401). "
                        "Re-generate your token in the LinkedIn Developer portal and update LINKEDIN_ACCESS_TOKEN."
                    ),
                )
            if e.response.status_code == 403:
                return ConnectorResult(
                    success=False,
                    message=f"LinkedIn permission denied (HTTP 403): {body}. "
                            "Ensure your app has the w_member_social scope and the token was granted that scope.",
                )
            return ConnectorResult(
                success=False,
                message=f"LinkedIn API error (HTTP {e.response.status_code}): {body}",
            )
        except Exception as e:
            return ConnectorResult(success=False, message=f"LinkedIn connector error: {e}")

    async def _resolve_person_urn(self) -> str:
        """Return the person URN from settings or fetch it from /v2/userinfo."""
        if settings.linkedin_person_urn:
            return settings.linkedin_person_urn

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(_USERINFO_URL, headers=_auth_headers())
            response.raise_for_status()
            data = response.json()

        sub = data.get("sub", "")
        if not sub:
            raise ValueError("LinkedIn /v2/userinfo returned no 'sub' field.")
        return f"urn:li:person:{sub}"


ConnectorRegistry.register(LinkedInConnector())
