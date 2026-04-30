"""
GitHub connector — push code and manage repositories via the GitHub REST API.

Handles three action types that require founder approval:
- github_push:        Push a single file via the Contents API
- github_create_pr:   Open a pull request
- github_create_repo: Create a new repository

Action field conventions
------------------------
github_push
  recipient : "owner/repo"
  subject   : "branch:path/to/file" or just "path/to/file" (defaults to main)
  content   : file content (the actual text to write)
  rationale : used as the commit message

github_create_pr
  recipient : "owner/repo"
  subject   : PR title
  content   : JSON string {"head": "feature-branch", "base": "main", "body": "PR description"}

github_create_repo
  recipient : org name, or empty string for the authenticated user's personal account
  subject   : repository name
  content   : repository description (plain text)

Setup
-----
  GITHUB_TOKEN=ghp_...  (personal access token or fine-grained token)
  Required scopes: repo (for private repos) or public_repo (for public repos only)
"""
from __future__ import annotations

import base64
import json

import httpx

from dri.config.settings import settings
from dri.connectors.base import BaseConnector, ConnectorResult
from dri.connectors.registry import ConnectorRegistry

_BASE_URL = "https://api.github.com"


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


class GitHubConnector(BaseConnector):
    """
    Executes GitHub actions approved by the founder.

    Requires GITHUB_TOKEN in .env with repo (or public_repo) scope.
    """

    def can_handle(self, action_type: str, action: dict) -> bool:
        return action_type in ("github_push", "github_create_pr", "github_create_repo")

    @property
    def is_configured(self) -> bool:
        return settings.has_github

    @property
    def setup_hint(self) -> str:
        return (
            "Set GITHUB_TOKEN in .env. "
            "Create one at github.com/settings/tokens — required scopes: repo (private) or public_repo."
        )

    async def execute(self, action: dict) -> ConnectorResult:
        if not self.is_configured:
            return ConnectorResult(
                success=False,
                message="GitHub connector not configured. Set GITHUB_TOKEN in .env.",
            )

        action_type = action.get("action_type", "")
        if action_type == "github_push":
            return await self._push_file(action)
        if action_type == "github_create_pr":
            return await self._create_pr(action)
        if action_type == "github_create_repo":
            return await self._create_repo(action)
        return ConnectorResult(success=False, message=f"Unknown GitHub action type: {action_type}")

    # ──────────────────────────────────────────────────────────
    # github_push
    # ──────────────────────────────────────────────────────────

    async def _push_file(self, action: dict) -> ConnectorResult:
        repo = action.get("recipient", "").strip()
        subject = action.get("subject", "").strip()
        file_content = action.get("content", "")
        commit_message = action.get("rationale", "Update file via DRI Agent")

        if not repo or "/" not in repo:
            return ConnectorResult(
                success=False,
                message="github_push: recipient must be 'owner/repo'.",
            )

        # Parse "branch:path" or just "path" (defaults to main)
        if ":" in subject:
            branch, file_path = subject.split(":", 1)
        else:
            branch, file_path = "main", subject

        if not file_path:
            return ConnectorResult(
                success=False,
                message="github_push: subject must contain the file path (e.g. 'main:src/app.py').",
            )

        encoded = base64.b64encode(file_content.encode()).decode()
        url = f"{_BASE_URL}/repos/{repo}/contents/{file_path.lstrip('/')}"

        # Check if file already exists (need SHA for updates)
        sha: str | None = None
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                get_resp = await client.get(url, headers=_auth_headers(), params={"ref": branch})
                if get_resp.status_code == 200:
                    sha = get_resp.json().get("sha")
        except Exception:
            pass

        payload: dict = {
            "message": commit_message,
            "content": encoded,
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.put(url, json=payload, headers=_auth_headers())
                resp.raise_for_status()

            action_word = "Updated" if sha else "Created"
            return ConnectorResult(
                success=True,
                message=f"{action_word} {file_path} on branch '{branch}' in {repo}.",
                details={"repo": repo, "branch": branch, "path": file_path},
            )
        except httpx.HTTPStatusError as e:
            body = e.response.text[:300]
            return ConnectorResult(
                success=False,
                message=f"GitHub push failed — HTTP {e.response.status_code}: {body}",
            )
        except Exception as e:
            return ConnectorResult(success=False, message=f"GitHub push error: {e}")

    # ──────────────────────────────────────────────────────────
    # github_create_pr
    # ──────────────────────────────────────────────────────────

    async def _create_pr(self, action: dict) -> ConnectorResult:
        repo = action.get("recipient", "").strip()
        pr_title = action.get("subject", "").strip()
        raw_content = action.get("content", "").strip()

        if not repo or "/" not in repo:
            return ConnectorResult(
                success=False,
                message="github_create_pr: recipient must be 'owner/repo'.",
            )
        if not pr_title:
            return ConnectorResult(
                success=False,
                message="github_create_pr: subject must be the PR title.",
            )

        # Parse content as JSON for head/base/body; fall back to plain body
        head = "main"
        base = "main"
        body = raw_content
        try:
            parsed = json.loads(raw_content)
            head = parsed.get("head", head)
            base = parsed.get("base", base)
            body = parsed.get("body", raw_content)
        except (json.JSONDecodeError, ValueError):
            pass  # content is plain text → use as PR body, keep head/base defaults

        if head == base:
            return ConnectorResult(
                success=False,
                message=(
                    f"github_create_pr: head and base are both '{head}'. "
                    "Provide different branches in content JSON: {\"head\": \"feature-branch\", \"base\": \"main\", \"body\": \"...\"}"
                ),
            )

        url = f"{_BASE_URL}/repos/{repo}/pulls"
        payload = {"title": pr_title, "head": head, "base": base, "body": body}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload, headers=_auth_headers())
                resp.raise_for_status()

            pr_data = resp.json()
            pr_url = pr_data.get("html_url", "")
            pr_number = pr_data.get("number", "?")
            return ConnectorResult(
                success=True,
                message=f"PR #{pr_number} created in {repo}: {pr_url}",
                external_id=str(pr_number),
                details={"url": pr_url, "number": pr_number},
            )
        except httpx.HTTPStatusError as e:
            body_err = e.response.text[:300]
            return ConnectorResult(
                success=False,
                message=f"GitHub create PR failed — HTTP {e.response.status_code}: {body_err}",
            )
        except Exception as e:
            return ConnectorResult(success=False, message=f"GitHub create PR error: {e}")

    # ──────────────────────────────────────────────────────────
    # github_create_repo
    # ──────────────────────────────────────────────────────────

    async def _create_repo(self, action: dict) -> ConnectorResult:
        org = action.get("recipient", "").strip()
        repo_name = action.get("subject", "").strip()
        description = action.get("content", "").strip()

        if not repo_name:
            return ConnectorResult(
                success=False,
                message="github_create_repo: subject must be the repository name.",
            )

        payload = {
            "name": repo_name,
            "description": description,
            "private": False,
            "auto_init": True,
        }

        url = f"{_BASE_URL}/orgs/{org}/repos" if org else f"{_BASE_URL}/user/repos"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload, headers=_auth_headers())
                resp.raise_for_status()

            repo_data = resp.json()
            html_url = repo_data.get("html_url", "")
            full_name = repo_data.get("full_name", repo_name)
            return ConnectorResult(
                success=True,
                message=f"Repository '{full_name}' created: {html_url}",
                external_id=full_name,
                details={"url": html_url, "full_name": full_name},
            )
        except httpx.HTTPStatusError as e:
            body_err = e.response.text[:300]
            return ConnectorResult(
                success=False,
                message=f"GitHub create repo failed — HTTP {e.response.status_code}: {body_err}",
            )
        except Exception as e:
            return ConnectorResult(success=False, message=f"GitHub create repo error: {e}")


ConnectorRegistry.register(GitHubConnector())
