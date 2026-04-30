"""
Memory system — four strictly separated layers:

1. Global store      — reads/writes via DB (AgentRepository, TaskRepository)
2. Context injection — parent builds a ContextPacket for each child at spawn time
3. Working memory    — ephemeral; lives only in the agent's active LLM prompt
4. Persistent memory — per-role adaptive knowledge in _knowledge/<slug>/ on disk

This module owns layers 2 and 4.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from dri.core.models import AgentConfig, AgentRole, Skill, Task, WorkspacePermission


def _title_slug(title: str) -> str:
    """Convert an agent title to a filesystem-safe slug (same rule as Spawner._slug)."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


class AgentMemory:
    """
    Persistent adaptive memory for an agent role.

    Stored at: <workspace>/<dept>/_knowledge/<title-slug>/
    Never touched by _cleanup_wip (which only removes _wip/ dirs).

    Files managed:
    - expertise.md  — accumulated domain knowledge, patterns, pitfalls
    - feedback.md   — feedback written by the parent manager after task review
    """

    _MAX_CHARS = 4000  # soft cap before truncation to protect context budget

    def __init__(self, knowledge_dir: Path) -> None:
        self._dir = knowledge_dir

    @classmethod
    def for_agent(
        cls,
        workspace_root: str,
        workspace_permissions: list[WorkspacePermission],
        title: str,
    ) -> "AgentMemory | None":
        """
        Factory. Returns None for ROOT/task-force agents that have no fixed department.
        Creates the knowledge directory on first use.
        """
        if not workspace_root:
            return None
        own_dept: str | None = None
        for perm in workspace_permissions:
            if perm.path and perm.path not in ("", "shared/") and perm.can_write:
                own_dept = perm.path
                break
        if not own_dept:
            return None
        knowledge_dir = (
            Path(workspace_root) / own_dept.rstrip("/") / "_knowledge" / _title_slug(title)
        )
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        return cls(knowledge_dir)

    def load(self) -> str:
        """
        Load all memory files and return a formatted string for system prompt injection.
        Returns empty string when no memory has been written yet.
        """
        parts: list[str] = []

        feedback = self._read("feedback.md")
        if feedback:
            parts.append(f"### Feedback from your manager\n{feedback}")

        expertise = self._read("expertise.md")
        if expertise:
            parts.append(f"### Your accumulated expertise\n{expertise}")

        if not parts:
            return ""

        combined = "\n\n".join(parts)
        if len(combined) > self._MAX_CHARS:
            combined = combined[: self._MAX_CHARS] + "\n[... memory truncated for context budget ...]"
        return combined

    @property
    def path(self) -> Path:
        return self._dir

    def _read(self, filename: str) -> str:
        f = self._dir / filename
        if not f.exists():
            return ""
        try:
            return f.read_text(encoding="utf-8").strip()
        except OSError:
            return ""


@dataclass
class ContextPacket:
    """
    Everything a child agent needs to know, assembled by its parent.
    Nothing else reaches the child — this is the isolation boundary.
    """

    agent_id: str
    title: str
    role: AgentRole
    mission: str
    parent_title: str
    skills: list[Skill] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    budget_tokens: int = 0
    model: str = ""
    company_name: str = ""
    company_pitch: str = ""
    prior_results: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    workspace_root: str = ""                                         # absolute path to company workspace
    workspace_permissions: list[WorkspacePermission] = field(default_factory=list)
    agent_memory: str = ""                                           # injected at task start from _knowledge/

    def to_system_prompt(self) -> str:
        """
        Render this context packet into the agent's system prompt.
        This is the only information the agent has about its existence.
        """
        lines: list[str] = []

        lines.append(f"# {self.title}")
        lines.append(f"\nYou are **{self.title}** at **{self.company_name or 'this company'}**.")
        lines.append(f"You report directly to **{self.parent_title}**.")
        lines.append("\n## Your Mission\n")
        lines.append(self.mission)

        if self.skills:
            lines.append("\n## Your Skills\n")
            for skill in self.skills:
                lines.append(skill.to_prompt_block())
                lines.append("")

        if self.constraints:
            lines.append("\n## Constraints\n")
            for c in self.constraints:
                lines.append(f"- {c}")

        if self.agent_memory:
            lines.append("\n## Your Persistent Memory\n")
            lines.append(
                "This is your accumulated knowledge from previous tasks. "
                "Apply it proactively — this expertise was earned through real work.\n"
            )
            lines.append(self.agent_memory)

        if self.prior_results:
            lines.append("\n## Relevant Prior Work\n")
            for r in self.prior_results:
                lines.append(r)
                lines.append("")

        if self.allowed_tools:
            lines.append("\n## Available Tools\n")
            lines.append(", ".join(self.allowed_tools))

        if self.workspace_root:
            lines.append("\n## Workspace\n")
            lines.append(f"Company workspace root: `{self.workspace_root}`")
            writable = [p for p in self.workspace_permissions if p.can_write]
            readable = [p for p in self.workspace_permissions if p.can_read and not p.can_write]
            if writable:
                paths = ", ".join(f"`{p.path or '(entire workspace)'}`" for p in writable)
                lines.append(f"You can **write** to: {paths}")
            if readable:
                paths = ", ".join(f"`{p.path or '(entire workspace)'}`" for p in readable)
                lines.append(f"You can **read** from: {paths}")
            lines.append(
                "Always save deliverables, reports, and outputs as files in your writable paths. "
                "Use paths relative to the workspace root (e.g. `marketing/report.md`)."
            )

        lines.append("\n## Operating Rules\n")
        lines.append(
            "- Focus exclusively on your assigned task. Do not scope-creep into other areas.\n"
            "- If you need something beyond your tools or budget, escalate to your manager.\n"
            "- When you complete your task, provide a clear, structured result.\n"
            "- Never communicate laterally with peers — only report upward to your manager.\n"
            f"- Your token budget for this task is {self.budget_tokens:,} tokens."
        )

        lines.append("\n## Integrity Rules — Mandatory, No Exceptions\n")
        lines.append(
            "- **NEVER fabricate data, outcomes, responses, or feedback.** "
            "If you lack a tool or capability to perform an action, do NOT invent what the result would be.\n"
            "- **For any action requiring real-world interaction** (sending emails, messages, posts, calls, outreach): "
            "use the `propose_external_action` tool. This logs the proposed action for founder approval. "
            "Do NOT proceed as if the action was executed — report upward that it is pending.\n"
            "- **When you don't know something**, say so. "
            "Use `web_search` to find real data, or escalate. An honest 'I could not find this' "
            "is always better than an invented answer.\n"
            "- **Mark hypotheticals explicitly.** Any example, template, or illustrative content "
            "that is not real data must be labeled `[EXAMPLE — NOT REAL DATA]`.\n"
            "- **Verify before citing.** Before finalizing your report, call `file_list` on your "
            "department folder to confirm which files actually exist on disk. "
            "NEVER mention a file in your report unless you have confirmed it exists. "
            "A file you intended to write but did not is a failure, not a result.\n"
            "- **Cite every file you produce.** In your report to your manager, list each file "
            "you created or modified with its exact workspace-relative path "
            "(e.g. `shared/report.md`, `marketing/strategy.md`). "
            "If you produced nothing, say so explicitly — do not invent deliverables."
        )

        lines.append("\n## File Lifecycle Rules\n")
        lines.append(
            "Files in the workspace are the company's source of truth. Keep them clean and current.\n\n"
            "**File zones — mandatory convention:**\n"
            "- `<your-dept>/_wip/` → ephemeral working files: drafts, notes, temp outputs. "
            "Save intermediate work here during execution.\n"
            "- `<your-dept>/` (root) and `shared/` → deliverables: final outputs that must "
            "persist after your task ends. Only save here when the work is complete.\n\n"
            "**Before reporting your task as complete:**\n"
            "- Delete everything inside your `_wip/` subfolder using `file_delete`.\n"
            "- Keep only final deliverables in your dept root and in `shared/`.\n\n"
            "**When to delete a deliverable:**\n"
            "- It has been superseded by a newer, complete version.\n"
            "- Its content contradicts the current company direction and no longer applies.\n\n"
            "**When NOT to delete:**\n"
            "- Files in another department's folder (you can read them, not delete them).\n"
            "- A file that is the only record of important context — update it instead.\n\n"
            "**How to delete properly:**\n"
            "- Use `file_delete` — never tell others to 'ignore' a file. Ignored files are clutter.\n"
            "- If a file is partially still relevant, overwrite it with `file_write`.\n"
            "- In your report, cite every file deleted: path + reason "
            "(e.g. `deleted shared/old_plan.md — superseded by shared/plan_v2.md`)."
        )

        return "\n".join(lines)


class ContextBuilder:
    """
    Builds ContextPackets. Used by the Spawner when creating child agents.
    The parent agent calls this to decide what the child should know.
    """

    @staticmethod
    def build(
        *,
        child_config: AgentConfig,
        parent_title: str,
        company_name: str,
        company_pitch: str,
        prior_results: list[str] | None = None,
        constraints: list[str] | None = None,
        workspace_root: str = "",
        workspace_permissions: list[WorkspacePermission] | None = None,
    ) -> ContextPacket:
        return ContextPacket(
            agent_id=child_config.id,
            title=child_config.title,
            role=child_config.role,
            mission=child_config.mission,
            parent_title=parent_title,
            skills=list(child_config.skills),
            allowed_tools=list(child_config.allowed_tools),
            budget_tokens=child_config.budget.total,
            model=child_config.model,
            company_name=company_name,
            company_pitch=company_pitch,
            prior_results=prior_results or [],
            constraints=constraints or [],
            metadata=dict(child_config.metadata),
            workspace_root=workspace_root,
            workspace_permissions=workspace_permissions or [],
        )

    @staticmethod
    def summarize_task_result(task: Task) -> str:
        """Format a completed task result for injection into a sibling/child context."""
        if task.result is None:
            return f"[Task '{task.description[:60]}' — no result]"
        return f"**{task.description[:80]}**\n{task.result[:500]}"
