"""
External action proposal tool.

Agents use this to propose actions that require real-world interaction
(email, outreach, social posts, calls). The action is logged to
`shared/_pending_approvals.json` for founder review — it is NEVER
executed immediately.

Workflow:
  1. Agent calls `propose_external_action` with full details.
  2. Action is written to the pending file with status "pending".
  3. Agent reports upward: "Action #N pending founder approval."
  4. Founder runs `dri company approvals list` to review.
  5. Founder runs `dri company approvals approve <N>` or `reject <N>`.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dri.tools.base import BaseTool, ToolOutput, ToolRegistry


class ProposeExternalActionTool(BaseTool):
    name = "propose_external_action"
    description = (
        "Propose an action that requires real-world interaction "
        "(sending an email, posting to Slack/Discord via webhook, social post, outreach). "
        "This logs the action for FOUNDER APPROVAL — it is NOT executed immediately. "
        "Use this instead of simulating or fabricating results. "
        "After calling this, stop and report to your manager that the action is pending approval."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action_type": {
                "type": "string",
                "enum": [
                    "email",
                    "sms",
                    "webhook",
                    "slack_message",
                    "linkedin_message",
                    "social_post",
                    "phone_call",
                    "outreach_message",
                    "bulk_file_delete",
                    "github_push",
                    "github_create_pr",
                    "github_create_repo",
                    "youtube_upload",
                    "youtube_create_playlist",
                    "other",
                ],
                "description": (
                    "Type of action requiring approval. "
                    "Use 'email' to send an email (recipient = email address). "
                    "Use 'sms' to send an SMS (recipient = phone number in +E.164 format). "
                    "Use 'slack_message' to post to a Slack channel or user "
                    "(recipient = #channel-name, channel ID like C12345, or user ID like U12345). "
                    "Use 'webhook' to POST to a Slack/Discord/Make.com/Zapier URL "
                    "(recipient = the full webhook URL). "
                    "Use 'social_post' for social media content. "
                    "Use 'bulk_file_delete' when file_delete is blocked by the bulk guard — "
                    "list every file path in content. "
                    "Use 'github_push' to push a file to a GitHub repo "
                    "(recipient=owner/repo, subject=branch:path/to/file, content=file_content, rationale=commit_message). "
                    "Use 'github_create_pr' to open a pull request "
                    "(recipient=owner/repo, subject=PR_title, content=JSON with head/base/body). "
                    "Use 'github_create_repo' to create a new repository "
                    "(recipient=org_or_empty, subject=repo_name, content=description). "
                    "Use 'youtube_upload' to upload a video file to YouTube "
                    "(recipient=channel_id_or_default, subject=video_title, content=description, "
                    "file_path=workspace-relative path to the .mp4 file e.g. 'shared/video.mp4'). "
                    "Video is uploaded as PRIVATE by default — founder controls visibility. "
                    "Use 'youtube_create_playlist' to create a new YouTube playlist "
                    "(subject=playlist_title, content=description)."
                ),
            },
            "recipient": {
                "type": "string",
                "description": (
                    "Who this action targets: name, email address, handle, or description. "
                    "Leave empty for bulk_file_delete (not applicable)."
                ),
            },
            "subject": {
                "type": "string",
                "description": "Subject line or title (for emails/posts). Leave empty if not applicable.",
            },
            "content": {
                "type": "string",
                "description": (
                    "The full text/body of the proposed action. "
                    "For bulk_file_delete: list every file path that will be deleted, one per line."
                ),
            },
            "rationale": {
                "type": "string",
                "description": "Why this action is proposed and what business outcome it targets.",
            },
            "file_path": {
                "type": "string",
                "description": (
                    "Optional. Workspace-relative path to a file to attach or upload "
                    "(e.g. 'shared/video.mp4'). Used for action_type='youtube_upload'. "
                    "Do not set for text-only actions."
                ),
            },
        },
        "required": ["action_type", "content", "rationale"],
    }

    _VALID_TYPES = frozenset(
        {"email", "sms", "webhook", "slack_message", "linkedin_message", "social_post", "phone_call", "outreach_message", "bulk_file_delete", "github_push", "github_create_pr", "github_create_repo", "youtube_upload", "youtube_create_playlist", "other"}
    )

    async def execute(self, raw_input: dict[str, Any]) -> ToolOutput:
        workspace_root: str = raw_input.get("_workspace_root", "")
        agent_title: str = raw_input.get("_agent_title", "Unknown Agent")
        company_name: str = raw_input.get("_company_name", "")

        if not workspace_root:
            return ToolOutput.fail(
                "propose_external_action requires a persistent company workspace. "
                "This tool only works within a `dri company chat` or `dri company task` session."
            )

        # Validate required fields before writing — empty actions are useless to the founder.
        action_type = raw_input.get("action_type", "other")

        # Enforce enum — reject any type the LLM invents outside the allowed set.
        if action_type not in self._VALID_TYPES:
            valid_list = ", ".join(sorted(self._VALID_TYPES))
            return ToolOutput.fail(
                f"Invalid action_type '{action_type}'. "
                f"You MUST use one of the allowed values: {valid_list}. "
                "For a LinkedIn post or social media content, use 'social_post'."
            )

        is_outreach = action_type not in ("bulk_file_delete", "other")
        missing: list[str] = []
        # recipient is required for all real-world outreach, not for internal ops
        if is_outreach and not raw_input.get("recipient", "").strip():
            missing.append("recipient (who this targets: name, email address, handle…)")
        content_val = raw_input.get("content", "").strip()
        if not content_val:
            if action_type == "bulk_file_delete":
                missing.append("content (list every file path that will be deleted, one per line)")
            else:
                missing.append("content (the full body/text of the message or action)")
        elif action_type in ("social_post", "email", "linkedin_message", "outreach_message"):
            # Reject indirect references — the founder must be able to read the exact content
            # without opening another file. "see file X" is not actionable.
            lowered = content_val.lower()
            if any(kw in lowered for kw in ("located at ", "see file", "refer to file", "in the file", "stored at ")):
                missing.append(
                    "content must be the FULL TEXT of the message — not a reference to another file. "
                    "Read the draft file and paste its complete content here."
                )
        if not raw_input.get("rationale", "").strip():
            missing.append("rationale (why this action is needed and what outcome it targets)")
        if missing:
            return ToolOutput.fail(
                "Cannot log action — the following required fields are empty:\n"
                + "\n".join(f"  - {m}" for m in missing)
                + "\n\nDo NOT call this tool again until you have filled in all fields with "
                "real, non-placeholder content. If you do not have the information, escalate "
                "to your manager instead of submitting an incomplete action."
            )

        shared_dir = Path(workspace_root) / "shared"
        shared_dir.mkdir(parents=True, exist_ok=True)
        pending_file = shared_dir / "_pending_approvals.json"

        existing: list[dict] = []
        if pending_file.exists():
            try:
                existing = json.loads(pending_file.read_text(encoding="utf-8"))
            except Exception:
                existing = []

        action_id = str(uuid.uuid4())
        entry = {
            "id": action_id,
            "status": "pending",
            "action_type": raw_input.get("action_type", "other"),
            "recipient": raw_input.get("recipient", ""),
            "subject": raw_input.get("subject", ""),
            "content": raw_input.get("content", ""),
            "rationale": raw_input.get("rationale", ""),
            "file_path": raw_input.get("file_path", ""),
            "proposed_by": agent_title,
            "company": company_name,
            "proposed_at": datetime.now(timezone.utc).isoformat(),
            "decided_at": None,
            "decision_note": None,
        }
        existing.append(entry)

        try:
            pending_file.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            return ToolOutput.fail(f"Failed to log pending action: {e}")

        return ToolOutput.ok({
            "action_id": action_id,
            "status": "pending_approval",
            "message": (
                f"Action #{action_id} ({raw_input.get('action_type', 'other')} to "
                f"'{raw_input.get('recipient', '')}') has been logged for founder approval. "
                "It has NOT been executed. "
                "Report to your manager that this action is pending founder approval with ID #"
                f"{action_id}. Do NOT proceed as if this action was completed."
            ),
        })


ToolRegistry.register(ProposeExternalActionTool())
