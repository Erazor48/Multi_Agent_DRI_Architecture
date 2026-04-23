"""
CompanyExecutor — manages persistent company lifecycle.

- create(pitch): designs the company, saves it to DB, returns PersistentCompany
- chat(company_id, message): sends a message to the persistent CEO, returns response
- task(company_id, task): spawns a full one-shot team to execute a task
"""
from __future__ import annotations

import json
from typing import Any

from dri.config.settings import settings
from dri.core.models import CompanyMessage, PersistentCompany
from dri.llm.factory import create_provider
from dri.storage.database import get_session, init_db
from dri.storage.repositories import CompanyMessageRepository, PersistentCompanyRepository


_COMPANY_DESIGN_TOOL = {
    "name": "design_company",
    "description": "Design the structure of this company.",
    "input_schema": {
        "type": "object",
        "properties": {
            "company_name": {"type": "string"},
            "company_vision": {"type": "string"},
            "departments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "mission": {"type": "string"},
                    },
                    "required": ["title", "mission"],
                },
            },
        },
        "required": ["company_name", "company_vision", "departments"],
    },
}

_SPAWN_TEAM_TOOL = {
    "name": "spawn_team",
    "description": (
        "Spawn a specialized team of agents to execute a concrete task. "
        "Use when the task requires real work: research, content creation, code, analysis, reports. "
        "Do NOT use for strategic discussion — only for actual execution."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_description": {
                "type": "string",
                "description": "Detailed description of what the team must deliver. Be specific.",
            },
        },
        "required": ["task_description"],
    },
}


class CompanyExecutor:

    @staticmethod
    async def create(pitch: str, on_status: Any = None) -> PersistentCompany:
        """Design a company from a pitch and persist it. Does not spawn agents."""
        await init_db()

        def _notify(msg: str) -> None:
            if on_status:
                on_status(msg)

        _notify("Designing company structure...")

        provider = create_provider()
        system = (
            "You are a world-class CEO and strategist. "
            "Design lean, effective company structures. Only the departments you truly need."
        )
        messages = [{
            "role": "user",
            "content": (
                f"## Company Pitch\n\n{pitch}\n\n"
                "Design this company by calling `design_company`. "
                "Be lean: 3-5 departments maximum."
            ),
        }]

        response = await provider.call(
            system=system,
            messages=messages,
            tools=[_COMPANY_DESIGN_TOOL],
            model=settings.root_model,
            max_tokens=4096,
        )

        design: dict[str, Any] = {}
        for tc in response.tool_calls:
            if tc.name == "design_company":
                design = tc.input
                break

        if not design:
            raise ValueError("LLM did not call design_company — try again.")

        company = PersistentCompany(
            name=design.get("company_name", "MyCompany"),
            vision=design.get("company_vision", ""),
            pitch=pitch,
            org_structure=design.get("departments", []),
        )

        async with get_session() as db:
            repo = PersistentCompanyRepository(db)
            await repo.create(company)

        _notify(f"Company '{company.name}' created.")
        return company

    @staticmethod
    async def chat(
        company_id: str,
        user_message: str,
        on_status: Any = None,
    ) -> str:
        """Send a message to the persistent CEO. Returns the CEO's response."""
        await init_db()

        def _notify(msg: str) -> None:
            if on_status:
                on_status(msg)

        async with get_session() as db:
            company_repo = PersistentCompanyRepository(db)
            msg_repo = CompanyMessageRepository(db)

            company = await company_repo.get(company_id)
            if company is None:
                raise ValueError(f"Company {company_id} not found.")

            history = await msg_repo.list_by_company(company_id)

        # Build system prompt
        dept_list = "\n".join(
            f"  - {d['title']}: {d.get('mission', '')}"
            for d in company.org_structure
        )
        system = (
            f"You are the CEO of **{company.name}**.\n"
            f"Vision: {company.vision}\n\n"
            f"Your departments:\n{dept_list}\n\n"
            "You are in a persistent, ongoing partnership with your founder (the user). "
            "You build this company together over time.\n\n"
            "For strategic discussion, planning, and questions — respond directly.\n"
            "For tasks requiring real execution (research, content, code, reports) — "
            "use the `spawn_team` tool to delegate to a specialized team.\n\n"
            "Always speak as the CEO: confident, concise, strategic."
        )

        # Build message history for LLM
        llm_messages: list[dict[str, Any]] = []
        for msg in history[-30:]:  # keep last 30 turns for context
            llm_messages.append({
                "role": "user" if msg.role == "user" else "assistant",
                "content": msg.content,
            })
        llm_messages.append({"role": "user", "content": user_message})

        # Save user message
        async with get_session() as db:
            msg_repo = CompanyMessageRepository(db)
            await msg_repo.add(CompanyMessage(
                company_id=company_id, role="user", content=user_message
            ))

        # CEO response loop (handles spawn_team)
        provider = create_provider()
        ceo_response = await _ceo_loop(
            provider=provider,
            system=system,
            messages=llm_messages,
            company=company,
            on_status=_notify,
        )

        # Save CEO response
        async with get_session() as db:
            msg_repo = CompanyMessageRepository(db)
            await msg_repo.add(CompanyMessage(
                company_id=company_id, role="ceo", content=ceo_response
            ))

        return ceo_response

    @staticmethod
    async def task(
        company_id: str,
        task_description: str,
        on_status: Any = None,
    ) -> str:
        """Directly spawn a one-shot team to execute a task for this company."""
        await init_db()

        async with get_session() as db:
            repo = PersistentCompanyRepository(db)
            company = await repo.get(company_id)
        if company is None:
            raise ValueError(f"Company {company_id} not found.")

        scoped_pitch = (
            f"You are a specialized task force working for **{company.name}**.\n"
            f"Company vision: {company.vision}\n\n"
            f"Your mission: {task_description}"
        )

        from dri.orchestration.executor import Executor
        executor = Executor()
        return await executor.run(scoped_pitch, on_status=on_status)


async def _ceo_loop(
    *,
    provider: Any,
    system: str,
    messages: list[dict[str, Any]],
    company: PersistentCompany,
    on_status: Any,
) -> str:
    """Run the CEO's agentic loop — handles spawn_team tool calls inline."""
    msgs = list(messages)

    for _ in range(5):  # max 5 spawn rounds
        response = await provider.call(
            system=system,
            messages=msgs,
            tools=[_SPAWN_TEAM_TOOL],
            model=settings.root_model,
            max_tokens=settings.max_tokens_per_response,
        )

        msgs.append(response.to_assistant_message())

        if not response.has_tool_calls:
            return response.text or "(No response)"

        # Handle spawn_team calls
        tool_results = []
        for tc in response.tool_calls:
            if tc.name == "spawn_team":
                task_desc = tc.input.get("task_description", "")
                on_status(f"Spawning team: {task_desc[:60]}...")

                scoped_pitch = (
                    f"Task force for **{company.name}** (vision: {company.vision}).\n\n"
                    f"Mission: {task_desc}"
                )
                from dri.orchestration.executor import Executor
                result = await Executor().run(scoped_pitch, on_status=on_status)
                tool_results.append({
                    "type": "tool_result",
                    "tool_call_id": tc.id,
                    "content": result,
                })
            else:
                tool_results.append({
                    "type": "tool_result",
                    "tool_call_id": tc.id,
                    "content": "Unknown tool.",
                })

        msgs.append({"role": "user", "content": tool_results})

    return response.text or "(Max rounds reached)"
