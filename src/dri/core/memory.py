"""
Memory system — three strictly separated layers:

1. Global store  — reads/writes via DB (AgentRepository, TaskRepository)
2. Context injection — parent builds a ContextPacket for each child at spawn time
3. Working memory — ephemeral; lives only in the agent's active LLM prompt

This module owns layer 2: constructing ContextPackets.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from dri.core.models import AgentConfig, AgentRole, Skill, Task, WorkspacePermission


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
            "- **Cite every file you produce.** In your report to your manager, list each file "
            "you created or modified with its exact workspace-relative path "
            "(e.g. `shared/startup_data.csv`, `marketing/report.md`)."
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
