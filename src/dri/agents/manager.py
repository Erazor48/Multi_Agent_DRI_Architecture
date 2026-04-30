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
from dri.config.settings import settings
from dri.core.models import AgentRole, AgentStatus, SpawnRequest, Task
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
                            "description": (
                                "Tool names to grant: web_search, code_exec, shell_exec, "
                                "file_read, file_write, file_list, file_delete, propose_external_action. "
                                "Grant shell_exec to workers who need to run system commands "
                                "(e.g. scaffold a Next.js app with bun, process media with ffmpeg, "
                                "run builds, install dependencies)."
                            ),
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


def _estimate_floor(tools: list[str]) -> int:
    """Minimum token budget per worker based on its assigned tools."""
    if "shell_exec" in tools:
        return 200_000   # scaffolding, builds, ffmpeg
    if "web_search" in tools:
        return 80_000    # research + synthesis
    if "code_exec" in tools:
        return 50_000    # Python scripts
    return 30_000        # file ops + writing


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
        parent_alloc = self._spawner._budget_manager.get_allocation(self.agent_id)
        parent_remaining = parent_alloc.remaining if parent_alloc else 0
        total_child_budget = int(parent_remaining * settings.budget_child_default_share)

        # Proportional allocation: LLM can request more budget for heavy workers via budget_share.
        # Shares are normalized so the total always sums to total_child_budget.
        shares = [float(m.get("budget_share", 1.0)) for m in team_members]
        total_share = sum(shares) or len(team_members)

        spawn_requests = []
        for member, share in zip(team_members, shares):
            role = AgentRole.WORKER if member.get("role", "worker") == "worker" else AgentRole.MANAGER
            skill_names = member.get("skills", [])
            skills = []
            for sn in skill_names:
                try:
                    skills.append(SkillCatalog.get(sn))
                except KeyError:
                    pass

            tools = member.get("tools", [])
            raw = int(total_child_budget * share / total_share)
            budget = max(raw, _estimate_floor(tools))

            req = SpawnRequest(
                parent_id=self.agent_id,
                parent_depth=self._ctx.metadata.get("depth", 0),
                role=role,
                title=member["title"],
                mission=member["mission"],
                skills=skills,
                allowed_tools=tools,
                budget_tokens=budget,
            )
            spawn_requests.append((req, member["task"]))

        # Step 3: Spawn agents and run them in parallel
        await self._registry.update_status(self.agent_id, AgentStatus.WAITING)

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
        worker_titles = [req.title for req, _ in spawn_requests]
        return await self._synthesize(task, results_text, synthesis_approach, worker_titles)

    async def _plan_org(self, task: Task) -> dict | None:
        """
        Ask the LLM to produce an org plan via tool call.
        Retries once with a stricter prompt if the LLM responds with text instead of a tool call.
        """
        base_content = (
            f"## Your Objective\n\n{task.description}"
            + (f"\n\n## Context\n\n{task.context}" if task.context else "")
        )
        prompts = [
            base_content + (
                "\n\nAnalyze this objective. Design your team by calling `create_org_plan`. "
                "Assign clear, non-overlapping missions. Choose worker for atomic tasks, "
                "manager for complex subtasks that need their own team."
            ),
            base_content + (
                "\n\n**You MUST call `create_org_plan` now.** Do not write a plan in text — "
                "use the tool. This is mandatory. Break the objective into team members, "
                "assign each a clear mission and task, then call the tool."
            ),
        ]

        for prompt in prompts:
            response = await self._call_llm([{"role": "user", "content": prompt}], tools=[_ORG_PLAN_TOOL])
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

    async def _synthesize(
        self,
        task: Task,
        results_text: str,
        approach: str,
        worker_titles: list[str] | None = None,
    ) -> str:
        """
        Synthesize all sub-results into a final report.

        Uses an agentic loop so the manager can call file_read on key deliverables
        before writing the synthesis — the result is grounded in actual file content,
        not just file names reported by workers.

        Also writes targeted feedback to each worker's _knowledge/ directory so
        they accumulate domain expertise over successive tasks.
        """
        dept_files = self._inventory_dept_files()
        shared_files = self._inventory_shared_files()
        all_files = sorted(set(dept_files + shared_files))
        file_inventory = ""
        if all_files:
            lines = ["**Files confirmed on disk (use file_read to read any of these):**"]
            for f in all_files:
                lines.append(f"  - {f}")
            file_inventory = "\n" + "\n".join(lines) + "\n"

        # Build per-worker feedback instructions
        feedback_note = ""
        if worker_titles:
            feedback_lines = [
                "\n**After completing the synthesis, write feedback for each team member.**",
                "For each worker below, use `file_write` to create/update their feedback file:",
            ]
            has_any = False
            for title in worker_titles:
                kpath = self._knowledge_path_str(title)
                if kpath:
                    feedback_lines.append(f"- **{title}** → `{kpath}/feedback.md`")
                    has_any = True
            if has_any:
                feedback_lines += [
                    "Each feedback file must contain:",
                    "  - What this worker did well in this task",
                    "  - Concrete improvements for next time (specific, actionable)",
                    "  - Domain patterns or rules they should remember",
                    "Read the existing file first (it may have prior feedback to preserve).",
                ]
                feedback_note = "\n".join(feedback_lines)

        messages = [
            {
                "role": "user",
                "content": (
                    f"## Original Objective\n\n{task.description}\n\n"
                    f"## Synthesis Approach\n\n{approach}\n\n"
                    f"## Team Results (summaries from workers)\n\n{results_text}\n"
                    f"{file_inventory}\n"
                    "Before writing the synthesis:\n"
                    "1. Use `file_read` to read the content of key deliverable files listed above "
                    "— do NOT rely only on the team summaries. Verify the actual content.\n"
                    "2. Then write a single, coherent, complete synthesis grounded in the real files.\n\n"
                    "Only cite files that appear in the confirmed inventory above. "
                    "Do not reference any file not listed there, even if a team member mentioned it.\n\n"
                    "If any team member was INTERRUPTED: acknowledge it explicitly, state what was "
                    "completed vs incomplete, list any files they left on disk, and recommend a "
                    "concrete next action (retry with narrower scope / reassign remaining work / "
                    "escalate). Do not silently skip failed subtasks.\n\n"
                    "Your manager expects a professional, structured report — not a list of summaries."
                    + feedback_note
                ),
            }
        ]
        result = await self._agentic_loop(messages, task.id)
        return result or results_text
