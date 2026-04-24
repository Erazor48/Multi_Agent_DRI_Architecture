"""
ManagerAgent — middle management in the org chart.

Responsibilities:
1. Receive a high-level task from its parent
2. Decide how to break it into subtasks
3. Spawn child agents (workers or sub-managers) in parallel
4. Collect and aggregate their results
5. Report a synthesized result upward

A manager can spawn other managers (for complex subtasks) or workers (for leaf tasks).
The LLM decides the breakdown — the manager is fully autonomous.
"""
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from dri.agents.base import BaseAgent
from dri.core.models import AgentRole, SpawnRequest, Task
from dri.skills.catalog import SkillCatalog

if TYPE_CHECKING:
    from dri.orchestration.spawner import Spawner


_ORG_PLAN_TOOL = {
    "name": "create_org_plan",
    "description": (
        "Create your team's org plan: define the subtasks, the roles needed to execute them, "
        "and whether each role should be a worker (leaf task) or sub-manager (complex subtask "
        "that itself needs a team). Call this once before spawning any agents."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "team_members": {
                "type": "array",
                "description": "List of team members to spawn.",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Job title (e.g. 'SEO Specialist')"},
                        "role": {
                            "type": "string",
                            "enum": ["worker", "manager"],
                            "description": "worker = leaf task; manager = needs a sub-team",
                        },
                        "mission": {"type": "string", "description": "One paragraph describing their mission"},
                        "task": {"type": "string", "description": "The specific task to assign them"},
                        "skills": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": f"Skill names from catalog: {SkillCatalog.names()}",
                        },
                        "tools": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tool names: web_search, code_exec, file_read, file_write, file_list, file_delete, propose_external_action",
                        },
                        "budget_share": {
                            "type": "number",
                            "description": "Fraction of manager's budget (0.0–1.0). Will be normalized.",
                        },
                    },
                    "required": ["title", "role", "mission", "task"],
                },
            },
            "synthesis_approach": {
                "type": "string",
                "description": "How you will synthesize the team's results into a final output.",
            },
        },
        "required": ["team_members", "synthesis_approach"],
    },
}


class ManagerAgent(BaseAgent):
    """
    A manager plans, delegates, supervises, and synthesizes.
    It never does leaf-level work directly.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._spawner: Spawner | None = None  # injected by Spawner after creation

    async def _run_task(self, task: Task) -> str:
        assert self._spawner is not None, "ManagerAgent requires a Spawner to be injected."

        # Step 1: Ask the LLM to plan the org and produce a tool call
        plan = await self._plan_org(task)
        if plan is None:
            # Fallback: no structured plan produced, handle as a direct task
            return await self._direct_response(task)

        team_members = plan.get("team_members", [])
        synthesis_approach = plan.get("synthesis_approach", "Synthesize all results.")

        if not team_members:
            return await self._direct_response(task)

        # Step 2: Spawn all team members — build all spawn requests first
        my_budget = self._budget_manager.get_allocation(self.agent_id)
        budget_per_child = self._spawner._budget_manager.compute_child_share(
            self.agent_id, len(team_members)
        )

        spawn_requests = []
        for member in team_members:
            role = AgentRole.WORKER if member.get("role", "worker") == "worker" else AgentRole.MANAGER
            skill_names = member.get("skills", [])
            skills = []
            for sn in skill_names:
                try:
                    skills.append(SkillCatalog.get(sn))
                except KeyError:
                    pass

            req = SpawnRequest(
                parent_id=self.agent_id,
                parent_depth=self._ctx.metadata.get("depth", 0),
                role=role,
                title=member["title"],
                mission=member["mission"],
                skills=skills,
                allowed_tools=member.get("tools", []),
                budget_tokens=budget_per_child,
            )
            spawn_requests.append((req, member["task"]))

        # Step 3: Spawn agents and run them in parallel
        await self._registry.update_status(
            self.agent_id, __import__("dri.core.models", fromlist=["AgentStatus"]).AgentStatus.WAITING
        )

        async def _spawn_and_run(req: SpawnRequest, task_description: str) -> str:
            child_task = Task(
                description=task_description,
                context=f"Parent context:\n{task.context}" if task.context else "",
                assigned_to="",      # will be set after spawn
                delegated_by=self.agent_id,
            )
            child_agent = await self._spawner.spawn(
                req,
                parent_title=self._ctx.title,
                constraints=[
                    f"Report directly to {self._ctx.title}.",
                    "Do not scope beyond your assigned task.",
                ],
            )
            child_task.assigned_to = child_agent.agent_id

            # Persist the child task
            from dri.storage.database import get_session
            from dri.storage.repositories import TaskRepository
            async with get_session() as db:
                task_repo = TaskRepository(db)
                await task_repo.create(self._session_id, child_task)

            report = await child_agent.run(child_task)
            return f"**{req.title}**: {report.result}" if report.result else f"**{req.title}**: [no result]"

        results = await asyncio.gather(
            *[_spawn_and_run(req, task_desc) for req, task_desc in spawn_requests],
            return_exceptions=True,
        )

        # Step 4: Synthesize results
        results_text = "\n\n".join(
            r if isinstance(r, str) else f"[Error: {r}]" for r in results
        )
        return await self._synthesize(task, results_text, synthesis_approach)

    async def _plan_org(self, task: Task) -> dict | None:
        """Ask the LLM to produce an org plan via tool call."""
        messages = [
            {
                "role": "user",
                "content": (
                    f"## Your Objective\n\n{task.description}"
                    + (f"\n\n## Context\n\n{task.context}" if task.context else "")
                    + "\n\nAnalyze this objective. Design your team by calling `create_org_plan`. "
                    "Assign clear, non-overlapping missions. Choose worker for atomic tasks, "
                    "manager for complex subtasks that need their own team."
                ),
            }
        ]

        response = await self._call_llm(messages, tools=[_ORG_PLAN_TOOL])

        for tc in response.tool_calls:
            if tc.name == "create_org_plan":
                return tc.input

        return None

    async def _direct_response(self, task: Task) -> str:
        """Fallback: handle the task directly without spawning."""
        messages = [
            {
                "role": "user",
                "content": (
                    f"## Task\n\n{task.description}"
                    + (f"\n\n## Context\n\n{task.context}" if task.context else "")
                    + "\n\nComplete this task directly and return a structured result."
                ),
            }
        ]
        return await self._agentic_loop(messages, task.id)

    async def _synthesize(self, task: Task, results_text: str, approach: str) -> str:
        """Ask the LLM to synthesize all sub-results into a final report."""
        messages = [
            {
                "role": "user",
                "content": (
                    f"## Original Objective\n\n{task.description}\n\n"
                    f"## Synthesis Approach\n\n{approach}\n\n"
                    f"## Team Results\n\n{results_text}\n\n"
                    "Synthesize these results into a single, coherent, complete output. "
                    "Your manager expects a professional, structured report — not a list of summaries."
                ),
            }
        ]
        response = await self._call_llm(messages)
        return response.text or results_text
