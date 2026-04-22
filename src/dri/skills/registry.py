"""
Per-agent skill registry — tracks which skills are active for a given agent.
Skills can be added or revoked at any time by the agent's parent.
"""
from __future__ import annotations

from dri.core.models import Skill


class SkillRegistry:
    """Runtime skill set for one agent instance."""

    def __init__(self, initial_skills: list[Skill] | None = None) -> None:
        self._skills: dict[str, Skill] = {}
        for skill in initial_skills or []:
            self.add(skill)

    def add(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def revoke(self, skill_name: str) -> None:
        self._skills.pop(skill_name, None)

    def has(self, skill_name: str) -> bool:
        return skill_name in self._skills

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def required_tools(self) -> set[str]:
        tools: set[str] = set()
        for skill in self._skills.values():
            tools.update(skill.required_tools)
        return tools

    def to_prompt_section(self) -> str:
        if not self._skills:
            return ""
        parts = ["## Your Skills\n"]
        for skill in self._skills.values():
            parts.append(skill.to_prompt_block())
            parts.append("")
        return "\n".join(parts)
