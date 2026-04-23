"""
RootAgent — the CEO. The only agent that speaks with the user.

Responsibilities:
1. Parse the user's company pitch
2. Design the top-level org structure (C-suite or equivalent)
3. Spawn top-level managers in parallel
4. Aggregate and return results to the user
5. Handle follow-up user messages
"""
from __future__ import annotations

import asyncio
from typing import Any

from dri.agents.base import BaseAgent
from dri.core.models import AgentRole, SpawnRequest, Task
from dri.skills.catalog import SkillCatalog


_COMPANY_DESIGN_TOOL = {
    "name": "design_company",
    "description": (
        "Design the top-level structure of the company. "
        "Define the company name, vision, and the top-level departments/roles "
        "that will form the first tier below the CEO. "
        "Each top-level role will be a manager who then builds their own team."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "company_name": {
                "type": "string",
                "description": "A memorable, relevant name for this company.",
            },
            "company_vision": {
                "type": "string",
                "description": "One sentence: what this company does and for whom.",
            },
            "departments": {
                "type": "array",
                "description": "Top-level departments/managers (C-suite or equivalent).",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "e.g. 'Chief Marketing Officer'"},
                        "mission": {"type": "string", "description": "One paragraph department mission"},
                        "initial_task": {"type": "string", "description": "First concrete task to kick off"},
                        "skills": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": f"Skill names: {SkillCatalog.names()}",
                        },
                    },
                    "required": ["title", "mission", "initial_task"],
                },
            },
            "initial_message_to_user": {
                "type": "string",
                "description": "Brief message to the user explaining what you're launching and why.",
            },
        },
        "required": ["company_name", "company_vision", "departments", "initial_message_to_user"],
    },
}


class RootAgent(BaseAgent):
    """
    The CEO agent. User-facing. Spawns and coordinates the entire company.
    Uses the root model (most capable) for all its LLM calls.
    """

    async def _run_task(self, task: Task) -> str:
        from dri.orchestration.spawner import Spawner

        assert hasattr(self, "_spawner"), "RootAgent requires a Spawner to be injected."

        # Step 1: Design the company
        design, initial_message = await self._design_company(task)
        if design is None:
            return await self._direct_response(task)

        # Update session with company name
        company_name = design.get("company_name", "Company")
        async with __import__("dri.storage.database", fromlist=["get_session"]).get_session() as db:
            from dri.storage.repositories import SessionRepository
            session_repo = SessionRepository(db)
            await session_repo.update_root_agent(
                self._session_id, self.agent_id, company_name
            )

        departments = design.get("departments", [])
        if not departments:
            return await self._direct_response(task)

        # Step 2: Spawn all C-suite managers in parallel
        budget_per_dept = self._spawner._budget_manager.compute_child_share(
            self.agent_id, len(departments)
        )

        async def _spawn_department(dept: dict) -> str:
            skill_names = dept.get("skills", ["team_management", "strategic_planning"])
            skills = []
            for sn in skill_names:
                try:
                    skills.append(SkillCatalog.get(sn))
                except KeyError:
                    pass

            req = SpawnRequest(
                parent_id=self.agent_id,
                parent_depth=0,
                role=AgentRole.MANAGER,
                title=dept["title"],
                mission=dept["mission"],
                skills=skills,
                allowed_tools=[],
                budget_tokens=budget_per_dept,
            )
            dept_task = Task(
                description=dept["initial_task"],
                context=f"Company: {company_name}\nVision: {design.get('company_vision', '')}",
                assigned_to="",
                delegated_by=self.agent_id,
            )
            dept_agent = await self._spawner.spawn(
                req,
                parent_title="CEO",
                constraints=[
                    "Report only to the CEO.",
                    "Build your team as needed to accomplish your mission.",
                    "Always synthesize your team's output before reporting upward.",
                ],
            )
            dept_task.assigned_to = dept_agent.agent_id

            from dri.storage.database import get_session
            from dri.storage.repositories import TaskRepository
            async with get_session() as db:
                task_repo = TaskRepository(db)
                await task_repo.create(self._session_id, dept_task)

            report = await dept_agent.run(dept_task)
            return f"## {dept['title']}\n\n{report.result or '[No result]'}"

        dept_results = await asyncio.gather(
            *[_spawn_department(dept) for dept in departments],
            return_exceptions=True,
        )

        results_text = "\n\n---\n\n".join(
            r if isinstance(r, str) else f"[Department error: {r}]"
            for r in dept_results
        )

        # Step 3: CEO synthesis
        final_report = await self._synthesize(
            task=task,
            company_name=company_name,
            vision=design.get("company_vision", ""),
            results_text=results_text,
        )

        return f"{initial_message}\n\n---\n\n{final_report}"

    async def _design_company(self, task: Task) -> tuple[dict | None, str]:
        """Ask the LLM to design the company structure via tool call."""
        messages = [
            {
                "role": "user",
                "content": (
                    f"## User's Company Pitch\n\n{task.description}\n\n"
                    "Design the company structure by calling `design_company`. "
                    "Think like a world-class CEO. Create only the departments you truly need — "
                    "lean and effective. Each department manager will build their own team."
                ),
            }
        ]
        response = await self._call_llm(
            messages,
            tools=[_COMPANY_DESIGN_TOOL],
            estimated_tokens=6000,
        )

        initial_message = response.text
        for tc in response.tool_calls:
            if tc.name == "design_company":
                return tc.input, initial_message

        return None, initial_message

    async def _direct_response(self, task: Task) -> str:
        messages = [
            {
                "role": "user",
                "content": task.description,
            }
        ]
        return await self._agentic_loop(messages, task.id)

    async def _synthesize(
        self, task: Task, company_name: str, vision: str, results_text: str
    ) -> str:
        messages = [
            {
                "role": "user",
                "content": (
                    f"## Company: {company_name}\n"
                    f"## Vision: {vision}\n\n"
                    f"## Original User Request\n\n{task.description}\n\n"
                    f"## Department Reports\n\n{results_text}\n\n"
                    "As CEO, write the final executive summary for the user. "
                    "Be specific, structured, and actionable. This is what the user sees."
                ),
            }
        ]
        response = await self._call_llm(messages, estimated_tokens=5000)
        return response.text or results_text
