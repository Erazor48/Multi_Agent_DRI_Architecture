"""
Memory system — three strictly separated layers:

1. Global store  — reads/writes via DB (AgentRepository, TaskRepository)
2. Context injection — parent builds a ContextPacket for each child at spawn time
3. Working memory — ephemeral; lives only in the agent's active LLM prompt

This module owns layer 2: constructing ContextPackets.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from dri.core.models import AgentConfig, AgentRole, Skill, Task


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
    prior_results: list[str] = field(default_factory=list)  # relevant completed task results
    constraints: list[str] = field(default_factory=list)    # rules injected by parent
    metadata: dict = field(default_factory=dict)

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

        lines.append("\n## Operating Rules\n")
        lines.append(
            "- Focus exclusively on your assigned task. Do not scope-creep into other areas.\n"
            "- If you need something beyond your tools or budget, escalate to your manager.\n"
            "- When you complete your task, provide a clear, structured result.\n"
            "- Never communicate laterally with peers — only report upward to your manager.\n"
            f"- Your token budget for this task is {self.budget_tokens:,} tokens."
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
        )

    @staticmethod
    def summarize_task_result(task: Task) -> str:
        """Format a completed task result for injection into a sibling/child context."""
        if task.result is None:
            return f"[Task '{task.description[:60]}' — no result]"
        return f"**{task.description[:80]}**\n{task.result[:500]}"
