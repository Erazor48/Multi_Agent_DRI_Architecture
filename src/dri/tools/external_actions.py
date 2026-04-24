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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dri.tools.base import BaseTool, ToolOutput, ToolRegistry


class ProposeExternalActionTool(BaseTool):
    name = "propose_external_action"
    description = (
        "Propose an action that requires real-world interaction "
        "(sending an email, LinkedIn message, social post, phone call, outreach). "
        "This logs the action for FOUNDER APPROVAL — it is NOT executed. "
        "Use this instead of simulating or fabricating results. "
        "After calling this, stop and report to your manager that the action is pending approval."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action_type": {
                "type": "string",
                "enum": ["email", "linkedin_message", "social_post", "phone_call", "outreach_message", "other"],
                "description": "Type of external action.",
            },
            "recipient": {
                "type": "string",
                "description": "Who this action targets: name, email address, handle, or description.",
            },
            "subject": {
                "type": "string",
                "description": "Subject line or title (for emails/posts). Leave empty if not applicable.",
            },
            "content": {
                "type": "string",
                "description": "The full text/body of the proposed message or action.",
            },
            "rationale": {
                "type": "string",
                "description": "Why this action is proposed and what business outcome it targets.",
            },
        },
        "required": ["action_type", "recipient", "content", "rationale"],
    }

    async def execute(self, raw_input: dict[str, Any]) -> ToolOutput:
        workspace_root: str = raw_input.get("_workspace_root", "")
        agent_title: str = raw_input.get("_agent_title", "Unknown Agent")
        company_name: str = raw_input.get("_company_name", "")

        if not workspace_root:
            return ToolOutput.fail(
                "propose_external_action requires a persistent company workspace. "
                "This tool only works within a `dri company chat` or `dri company task` session."
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

        action_id = len(existing) + 1
        entry = {
            "id": action_id,
            "status": "pending",
            "action_type": raw_input.get("action_type", "other"),
            "recipient": raw_input.get("recipient", ""),
            "subject": raw_input.get("subject", ""),
            "content": raw_input.get("content", ""),
            "rationale": raw_input.get("rationale", ""),
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
