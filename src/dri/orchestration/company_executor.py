"""
CompanyExecutor — manages persistent company lifecycle.

- create(pitch): designs the company, saves it to DB, returns PersistentCompany
- chat(company_id, message): sends a message to the persistent CEO, returns response
- task(company_id, task): spawns a full one-shot team to execute a task
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from dri.config.settings import settings
from dri.core.models import CompanyMessage, PersistentCompany
from dri.llm.factory import create_provider
from dri.storage.database import get_session, init_db
from dri.storage.repositories import CompanyMessageRepository, PersistentCompanyRepository


def _company_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _company_workspace(name: str) -> str:
    return str(settings.workspace_dir / _company_slug(name))


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
        "Spawn a specialized team of agents to execute a concrete task within this company. "
        "Use when the task requires real work: research, content creation, code, analysis, reports. "
        "Do NOT use for strategic discussion — only for actual execution. "
        "Spawn a team ONCE per objective. If a team already produced a result, build on it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_description": {
                "type": "string",
                "description": (
                    "Detailed description of what the team must deliver. Be specific. "
                    "Include any relevant context from existing workspace files."
                ),
            },
        },
        "required": ["task_description"],
    },
}

# Read-only tools for the CEO — lets it inspect the workspace before making decisions.
# The CEO never writes files directly; it delegates execution to task forces.
_CEO_READ_TOOLS = [
    {
        "name": "file_list",
        "description": (
            "List files in the company workspace. "
            "Use '.' for the root, or a subfolder path "
            "(e.g. 'shared', 'chief-marketing-officer'). "
            "Call this to understand what already exists before deciding what to delegate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path relative to workspace root. Use '.' for root.",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "List all nested files.",
                    "default": False,
                },
            },
        },
    },
    {
        "name": "file_read",
        "description": "Read the content of a file in the company workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to workspace root.",
                },
            },
            "required": ["path"],
        },
    },
]


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

        # Create workspace directory structure
        workspace_root = settings.workspace_dir / _company_slug(company.name)
        (workspace_root / "shared").mkdir(parents=True, exist_ok=True)
        (workspace_root / "ceo").mkdir(parents=True, exist_ok=True)
        for dept in company.org_structure:
            dept_slug = _company_slug(dept.get("title", "dept"))
            (workspace_root / dept_slug).mkdir(parents=True, exist_ok=True)

        _notify(f"Company '{company.name}' created. Workspace: {workspace_root}")
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

        workspace_root = _company_workspace(company.name)

        dept_list = "\n".join(
            f"  - {d['title']}: {d.get('mission', '')}"
            for d in company.org_structure
        )
        dept_folders = "\n".join(
            f"  - {_company_slug(d['title'])}/"
            for d in company.org_structure
        )

        system = (
            f"You are the CEO of **{company.name}**.\n"
            f"Vision: {company.vision}\n\n"
            f"Your departments:\n{dept_list}\n\n"
            f"Official workspace folders:\n  - shared/\n{dept_folders}\n\n"
            "You are in a persistent, ongoing partnership with your founder (the user). "
            "You build this company together over time.\n\n"

            "## Before responding — always do this first\n"
            "1. Look at the verified workspace snapshot injected at the top of the founder's "
            "message. That is the ground truth — not your memory.\n"
            "2. Re-read the founder's last messages and list every task explicitly requested. "
            "Do NOT respond until you know exactly what was asked.\n"
            "3. For each task: determine if it is DONE, FAILED, or PENDING based on the "
            "workspace snapshot — not on what a team claimed.\n\n"

            "## Execution rules — mandatory\n"
            "- For tasks requiring real work (research, content, code, analysis, file edits): "
            "call `spawn_team` NOW in this response — do NOT describe launching a team "
            "without actually calling the tool. 'Je mandate une équipe' without a spawn_team "
            "call is fabrication and is strictly forbidden.\n"
            "- For discussion and questions: respond directly without spawn_team.\n"
            "- **After every spawn_team**: use `file_read` on each key deliverable to verify "
            "its content is real and complete — not empty, not placeholder, not fabricated. "
            "A file that exists but contains fake or template data counts as FAILED.\n"
            "- **Re-spawn if clearly wrong**: if a team's deliverable is empty or wrong, "
            "spawn again with a more precise task. You do not have to accept bad results — "
            "but after two failed attempts on the same task, stop and tell the founder why.\n"
            "- **Complete tasks in order**: do not move on to task N+1 while task N is "
            "incomplete or unverified. If the founder adds a new request while you are "
            "working, acknowledge it and finish the current task first.\n"
            "- **Surface failures honestly**: if a task could not be completed (budget, "
            "missing data, blocked tool), say exactly what failed and why. "
            "Never present incomplete work as done.\n"
            "- **Budget**: if a spawn_team reports token budget exhaustion, tell the founder "
            "immediately — do not silently retry or pretend the work was done.\n"
            "- Your teams have `web_search` — never ask the founder to provide external "
            "data if teams can research it themselves.\n\n"

            "## Workspace cleanup — strict scope\n"
            "When the founder asks to 'clean', 'fix', or 'tidy' the workspace:\n"
            "- This means: identify and fix SPECIFIC problems, preserve everything else.\n"
            "- It NEVER means: delete all files, wipe departments, or start from zero.\n"
            "- Rogue folders (not in the official list above) may be removed, but ONLY "
            "after using `file_list` to confirm they are truly empty or obsolete.\n"
            "- Deleting a folder with more than 3 files is blocked by the system — you "
            "must use `propose_external_action` with action_type='bulk_file_delete', "
            "listing every file with its rationale, and wait for founder approval.\n\n"

            "## Integrity rules — no exceptions\n"
            "- NEVER invent data, file paths, or results. If you did not verify it, "
            "do not claim it.\n"
            "- Only mention a file if it appears in the verified workspace snapshot.\n"
            "- Real-world actions (emails, outreach, posts) must go through "
            "`propose_external_action` inside a spawned team — report the pending "
            "action ID to the founder, then stop.\n"
            "- Cite every file with its exact workspace-relative path "
            "(e.g. `shared/report.md`, `croissance-strat-gie/targets.md`).\n\n"

            "Always speak as the CEO: direct, honest, concise. "
            "A short honest failure report is better than a long fabricated success."
        )

        llm_messages: list[dict[str, Any]] = []
        for msg in history[-30:]:
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

        provider = create_provider()
        ceo_response = await _ceo_loop(
            provider=provider,
            system=system,
            messages=llm_messages,
            company=company,
            workspace_root=workspace_root,
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

        workspace_root = _company_workspace(company.name)

        return await _run_task_force(
            company=company,
            task_description=task_description,
            workspace_root=workspace_root,
            on_status=on_status or (lambda _: None),
        )


async def _ceo_loop(
    *,
    provider: Any,
    system: str,
    messages: list[dict[str, Any]],
    company: PersistentCompany,
    workspace_root: str,
    on_status: Any,
) -> str:
    """
    Run the CEO's agentic loop.

    Handles three tool types inline:
    - spawn_team: delegates to _run_task_force (a ManagerAgent in the existing company workspace)
    - file_list / file_read: executed directly against the company workspace (read-only)
    """
    import dri.tools  # noqa: F401 — ensure ToolRegistry is populated
    from dri.tools.base import ToolRegistry

    msgs = list(messages)
    all_ceo_tools = [_SPAWN_TEAM_TOOL] + _CEO_READ_TOOLS
    # CEO has read-only access to the entire workspace
    ceo_permissions = [{"path": "", "can_read": True, "can_write": False, "can_delete": False}]

    # Inject the real workspace state into the current user turn before the first LLM call.
    # This ensures the CEO always starts from ground truth — never from stale memory.
    if msgs and msgs[-1].get("role") == "user":
        snapshot = _workspace_snapshot(workspace_root)
        original = msgs[-1]["content"]
        msgs[-1] = {
            **msgs[-1],
            "content": f"**Current workspace (verified on disk):**\n{snapshot}\n\n---\n\n{original}",
        }

    for _ in range(10):  # allow file inspection rounds before and between spawns
        response = await provider.call(
            system=system,
            messages=msgs,
            tools=all_ceo_tools,
            model=settings.root_model,
            max_tokens=settings.max_tokens_per_response,
        )

        msgs.append(response.to_assistant_message())

        if not response.has_tool_calls:
            return response.text or "(No response)"

        tool_results = []
        for tc in response.tool_calls:
            if tc.name == "spawn_team":
                task_desc = tc.input.get("task_description", "")
                on_status(f"Spawning team: {task_desc[:60]}...")
                result = await _run_task_force(
                    company=company,
                    task_description=task_desc,
                    workspace_root=workspace_root,
                    on_status=on_status,
                )
                # Append a verified workspace snapshot so the CEO can only cite files
                # that actually exist — never trust team reports alone.
                result += "\n\n---\n" + _workspace_snapshot(workspace_root)
                tool_results.append({
                    "type": "tool_result",
                    "tool_call_id": tc.id,
                    "tool_name": tc.name,
                    "content": result,
                })

            elif tc.name in ("file_list", "file_read"):
                tool_input = dict(tc.input or {})
                tool_input["_workspace_root"] = workspace_root
                tool_input["_permissions"] = ceo_permissions
                try:
                    tool = ToolRegistry.get(tc.name)
                    output = await tool.execute(tool_input)
                    content = json.dumps(output.data) if output.success else f"Error: {output.error}"
                except Exception as e:
                    content = f"Tool error: {e}"
                tool_results.append({
                    "type": "tool_result",
                    "tool_call_id": tc.id,
                    "tool_name": tc.name,
                    "content": content,
                })

            else:
                tool_results.append({
                    "type": "tool_result",
                    "tool_call_id": tc.id,
                    "tool_name": tc.name,
                    "content": "Unknown tool.",
                })

        msgs.append({"role": "user", "content": tool_results})

    return response.text or "(Max rounds reached)"


def _workspace_snapshot(workspace_root: str) -> str:
    """
    Return a verified listing of every deliverable file currently on disk.
    Injected after every spawn_team result so the CEO never cites phantom files.
    """
    from pathlib import Path as _Path
    ws = _Path(workspace_root)
    if not ws.exists():
        return "**Workspace snapshot:** (workspace not found)"
    files = sorted(
        f.relative_to(ws).as_posix()
        for f in ws.rglob("*")
        if f.is_file() and "_wip" not in f.parts
    )
    if not files:
        return "**Workspace snapshot (verified on disk):** no files yet."
    lines = ["**Workspace snapshot (verified on disk — cite only from this list):**"]
    lines += [f"  - {p}" for p in files]
    return "\n".join(lines)


async def _run_task_force(
    *,
    company: PersistentCompany,
    task_description: str,
    workspace_root: str,
    on_status: Any,
) -> str:
    """
    Run a task force WITHIN the existing persistent company's workspace.

    Creates a ManagerAgent session scoped to this company — NOT a new company.
    Workers receive ROOT workspace access (they act on behalf of the CEO and need
    to operate across any folder, e.g. for cleanup of rogue artifacts).
    """
    from dri.core.budget import BudgetManager
    from dri.core.communication import CommunicationBus
    from dri.core.memory import ContextBuilder
    from dri.core.models import (
        AgentConfig,
        AgentRole,
        AgentState,
        AgentStatus,
        BudgetAllocation,
        Session,
        Task,
        WorkspacePermission,
    )
    from dri.core.registry import AgentRegistry
    from dri.orchestration.spawner import Spawner
    from dri.storage.repositories import AgentRepository, SessionRepository, TaskRepository
    from dri.agents.manager import ManagerAgent

    # Create a minimal session so agent/task DB writes have a valid session_id
    session = Session(
        company_pitch=company.pitch,
        budget_max_tokens=settings.budget_max_tokens_per_session,
    )
    async with get_session() as db:
        session_repo = SessionRepository(db)
        await session_repo.create(session)
        await session_repo.update_status(session.id, "running")

    budget = settings.budget_max_tokens_per_session
    budget_manager = BudgetManager(budget)
    registry = AgentRegistry(session_id=session.id, root_agent_id="")
    bus = CommunicationBus()

    official_folders = ["shared/", "ceo/"] + [
        f"{_company_slug(d.get('title', ''))}/"
        for d in company.org_structure
    ]
    official_folders_str = "\n".join(f"  - {f}" for f in official_folders)

    config = AgentConfig(
        role=AgentRole.MANAGER,
        title="Task Force Lead",
        allowed_tools=["file_list", "file_read", "file_write", "file_delete", "propose_external_action"],
        mission=(
            f"You are a task force lead for **{company.name}**.\n"
            f"Company vision: {company.vision}\n\n"
            f"Official workspace folders:\n{official_folders_str}\n"
            "Any folder NOT in this list is a rogue artifact and must be deleted during cleanup.\n\n"
            f"Your task: {task_description}\n\n"
            "Before designing your team, use `file_list` on the workspace root to check "
            "what exists — identify rogue folders and build on existing work, do not redo it.\n\n"
            "## Tool allocation rules for your team\n"
            "- Assign `propose_external_action` to any worker that needs to propose a real-world "
            "action (email, LinkedIn post, social media, outreach). That tool logs the action for "
            "founder approval — it does NOT execute it immediately.\n"
            "- Assign `web_search` to workers that need external research.\n"
            "- File tools (file_list, file_read, file_write, file_delete) are added automatically.\n\n"
            "## Rules for propose_external_action\n"
            "- action_type MUST be one of: email, sms, webhook, slack_message, linkedin_message, "
            "social_post, phone_call, outreach_message, bulk_file_delete, other. Never invent a new type.\n"
            "- Use 'email' when recipient is an email address.\n"
            "- Use 'slack_message' when posting to a Slack channel or user "
            "(recipient = #channel-name, channel ID like C12345, or user ID like U12345). "
            "This is the preferred type for Slack — do NOT use 'webhook' for Slack channels.\n"
            "- Use 'sms' when recipient is a phone number in E.164 format (+33XXXXXXXXX).\n"
            "- Use 'webhook' when recipient is an HTTP/HTTPS URL (Make.com/Zapier/Discord/custom). "
            "The system will POST the content immediately on approval.\n"
            "- content MUST be the FULL TEXT of the message — not a reference to a file. "
            "If you saved a draft to a file, read it back with file_read and paste the entire text "
            "into content before calling propose_external_action.\n"
            "- recipient MUST be specific: an email address, a webhook URL, or a platform handle."
        ),
        parent_id=None,
        depth=0,
        model=settings.default_model,
        budget=BudgetAllocation(total=budget),
    )
    state = AgentState(config=config, status=AgentStatus.INITIALIZING)
    registry._root_agent_id = config.id

    async with get_session() as db:
        agent_repo = AgentRepository(db)
        await agent_repo.create(session.id, state)

    await registry.register(state)
    await budget_manager.allocate(config.id, budget)

    # Task force lead has full workspace access — acts on behalf of the CEO
    ws_perms = [WorkspacePermission(path="", can_read=True, can_write=True, can_delete=True)]

    spawner = Spawner(
        session_id=session.id,
        company_name=company.name,
        company_pitch=company.pitch,
        registry=registry,
        bus=bus,
        budget_manager=budget_manager,
        workspace_root=workspace_root,
        root_workspace_access=True,  # task force workers act on CEO authority
    )

    context = ContextBuilder.build(
        child_config=config,
        parent_title="CEO",
        company_name=company.name,
        company_pitch=company.pitch,
        workspace_root=workspace_root,
        workspace_permissions=ws_perms,
    )

    manager = ManagerAgent(
        context=context,
        session_id=session.id,
        registry=registry,
        bus=bus,
        budget_manager=budget_manager,
    )
    manager._spawner = spawner  # type: ignore[attr-defined]

    task = Task(
        description=task_description,
        context=f"Company: {company.name}\nVision: {company.vision}",
        assigned_to=config.id,
        delegated_by="ceo",
    )

    async with get_session() as db:
        task_repo = TaskRepository(db)
        await task_repo.create(session.id, task)

    on_status(f"Task force active: {task_description[:80]}...")
    report = await manager.run(task)

    # All workers are done — remove any _wip/ dirs that workers left behind.
    # Workers with root_workspace_access have _cleanup_wip() that cleans everything,
    # but this is a belt-and-suspenders guarantee at the task-force boundary.
    import shutil as _shutil
    from pathlib import Path as _Path
    for wip_dir in sorted(_Path(workspace_root).rglob("_wip"), reverse=True):
        if wip_dir.is_dir():
            _shutil.rmtree(str(wip_dir), ignore_errors=True)

    async with get_session() as db:
        session_repo = SessionRepository(db)
        await session_repo.complete(session.id)

    return report.result or "[Task force produced no result]"
