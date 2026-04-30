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
from dri.storage.repositories import CompanyAgentRepository, CompanyMessageRepository, PersistentCompanyRepository


# ── Conversation summarization thresholds ────────────────────────────────
# When regular (non-summary) message count exceeds this, compress old messages.
_SUMMARY_THRESHOLD = 40
# Most recent messages kept verbatim after each compression round.
_SUMMARY_KEEP_VERBATIM = 14


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

        # Load task history for CEO context (Layer 6 — Gap 2 fix)
        from pathlib import Path as _Path
        _history_path_chat = _Path(workspace_root) / "shared" / "_company_history.md"
        _ceo_history_section = ""
        if _history_path_chat.exists():
            try:
                _hist = _history_path_chat.read_text(encoding="utf-8").strip()
                if _hist:
                    _ceo_history_section = (
                        "\n\n## Company Task History\n"
                        "Recent tasks executed by your teams (most recent last):\n"
                        f"{_hist[-3000:]}"
                    )
            except OSError:
                pass

        # Compress history if it's grown too long.
        # _notify suppressed here — summarization is transparent to the user.
        provider_for_summary = create_provider()
        did_summarize = await _maybe_summarize_ceo_history(
            company_id=company_id,
            history=history,
            provider=provider_for_summary,
            company=company,
        )
        if did_summarize:
            async with get_session() as db:
                msg_repo2 = CompanyMessageRepository(db)
                history = await msg_repo2.list_by_company(company_id)

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

            "## PLATFORM CAPABILITIES — read this before anything else\n"
            "Your task force workers have a real shell executor: `shell_exec`.\n"
            "This is verified and functional. Workers CAN:\n"
            "  - Scaffold a real Next.js project: `bun create next-app@latest my-app --yes`\n"
            "  - Install dependencies: `bun install`, `npm install`\n"
            "  - Build projects: `bun run build`\n"
            "  - Process media: `ffmpeg -i input.mp4 output.mp4`\n"
            "  - Run Python scripts: `uv run script.py`\n"
            "RULE: NEVER tell the founder to run commands manually. "
            "NEVER say your teams 'cannot execute' shell commands. "
            "If prior messages say otherwise, those are outdated — shell_exec is available NOW. "
            "Spawn a team with shell_exec to do any scaffolding or build task.\n\n"

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
            "data if teams can research it themselves.\n"
            "- Your teams have `shell_exec` — they can scaffold real projects (Next.js via "
            "'bun create next-app@latest'), install deps ('bun install'), run builds "
            "('bun run build'), and process media (ffmpeg). NEVER ask the founder to run "
            "terminal commands manually when a worker with shell_exec can do it.\n"
            "- **Next.js / Turbopack quality gate**: your workers MUST run `bun run build` "
            "after every frontend change and fix ALL errors before reporting done. "
            "A project with a failing build is NOT done — re-spawn with stricter instructions. "
            "Build output from Turbopack includes exact error locations; workers must read and fix every one.\n"
            "- When a team delivers a runnable project, always surface the launch commands "
            "in your response using a code block — e.g. `cd <path> && bun run dev`. "
            "The founder must be able to copy-paste a single command to start the project.\n\n"

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

            "## Company knowledge base — `shared/_company_knowledge.md`\n"
            "This file is the company's institutional memory. Every task force reads it.\n"
            "After a significant decision, strategic pivot, or completed milestone, "
            "spawn a minimal one-worker team to update it with:\n"
            "  ## Strategic Decisions — key directional choices\n"
            "  ## Brand & Voice — positioning, tone, target audience\n"
            "  ## Technical Stack — tools, frameworks, infrastructure decisions\n"
            "  ## Completed Milestones — what's been shipped\n"
            "  ## Lessons Learned — what worked, what to avoid\n"
            "You can read the current version with `file_read` on `shared/_company_knowledge.md`.\n\n"

            "Always speak as the CEO: direct, honest, concise. "
            "A short honest failure report is better than a long fabricated success."
        ) + _ceo_history_section

        llm_messages = _build_ceo_messages(history, user_message)

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


async def _maybe_summarize_ceo_history(
    *,
    company_id: str,
    history: list[Any],
    provider: Any,
    company: Any,
) -> bool:
    """
    If regular message count exceeds _SUMMARY_THRESHOLD, compress the oldest messages
    into a summary record. Deletes compressed messages from DB and inserts one summary.
    Returns True if summarization happened (caller should reload history).
    """
    summaries = [m for m in history if m.role == "summary"]
    regular = [m for m in history if m.role != "summary"]

    if len(regular) <= _SUMMARY_THRESHOLD:
        return False

    to_summarize = regular[:-_SUMMARY_KEEP_VERBATIM]
    existing_summary = summaries[0].content if summaries else ""

    conversation_text = "\n\n".join(
        f"{'[FOUNDER]' if m.role == 'user' else '[CEO]'}: {m.content[:700]}"
        for m in to_summarize
    )

    prompt = (
        (f"## Prior summary to update\n{existing_summary}\n\n" if existing_summary else "")
        + f"## Conversation to incorporate — company: {company.name}\n{conversation_text}\n\n"
        "Produce a structured summary with these exact sections:\n\n"
        "## Strategic Decisions\nKey decisions about direction, positioning, products.\n\n"
        "## Completed Work\nTasks completed, with workspace file paths where relevant.\n\n"
        "## Founder Preferences\nInstructions, preferences, or constraints the founder expressed.\n\n"
        "## Open Issues & Next Steps\nUnresolved problems, pending tasks, known blockers.\n\n"
        "Be specific. Include file paths. Max 300 lines."
    )

    response = await provider.call(
        system=(
            "You compress AI agent conversation histories into dense, accurate summaries "
            "that preserve all decision-relevant context."
        ),
        messages=[{"role": "user", "content": prompt}],
        tools=None,
        model=settings.default_model,
        max_tokens=4096,
    )

    summary_text = response.text or "(summary unavailable)"
    ids_to_delete = [m.id for m in to_summarize + summaries]

    async with get_session() as db:
        msg_repo = CompanyMessageRepository(db)
        await msg_repo.replace_with_summary(company_id, ids_to_delete, summary_text)

    return True


def _build_ceo_messages(
    history: list[Any],
    current_user_message: str,
) -> list[dict[str, Any]]:
    """
    Build the LLM message list from history.

    Summary records are injected as a context prefix on the first user message.
    Regular messages are taken verbatim (last _SUMMARY_KEEP_VERBATIM).
    Always ends with the current user message.
    """
    summaries = [m for m in history if m.role == "summary"]
    regular = [m for m in history if m.role != "summary"]

    # Take only recent messages to stay within context budget
    recent = regular[-_SUMMARY_KEEP_VERBATIM:]

    # Drop any leading assistant messages so the sequence starts with "user"
    while recent and recent[0].role != "user":
        recent = recent[1:]

    llm_messages: list[dict[str, Any]] = []
    for i, msg in enumerate(recent):
        role = "user" if msg.role == "user" else "assistant"
        content = msg.content
        # Prepend the summary to the first user message in the window
        if i == 0 and summaries:
            content = (
                "[Summary of prior conversation — treat as established context]\n\n"
                f"{summaries[0].content}\n\n---\n\n{content}"
            )
        llm_messages.append({"role": role, "content": content})

    llm_messages.append({"role": "user", "content": current_user_message})
    return llm_messages


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

    for _ in range(20):  # allow file inspection rounds before and between spawns
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
    _INFRA = {"_audit.log", "_pending_approvals.json"}
    _SKIP_DIRS = {"node_modules", ".next", ".git", "__pycache__", ".venv", "venv", "dist", "build", ".cache", "_knowledge"}
    files = sorted(
        f.relative_to(ws).as_posix()
        for f in ws.rglob("*")
        if f.is_file()
        and "_wip" not in f.parts
        and f.name not in _INFRA
        and not any(part in _SKIP_DIRS for part in f.parts)
    )
    if not files:
        return "**Workspace snapshot (verified on disk):** no files yet."
    lines = ["**Workspace snapshot (verified on disk — cite only from this list):**"]
    lines += [f"  - {p}" for p in files]
    return "\n".join(lines)


def _append_company_history(
    *,
    workspace_root: str,
    task_description: str,
    registry: Any,
    report: Any,
    tokens_total: int,
) -> None:
    """Append one entry to shared/_company_history.md (Layer 6). Non-critical — errors are swallowed."""
    from datetime import datetime, timezone
    from pathlib import Path as _Path
    from dri.core.models import AgentStatus as _AgentStatus, TaskStatus as _TaskStatus

    try:
        ws = _Path(workspace_root)
        history_file = ws / "shared" / "_company_history.md"
        history_file.parent.mkdir(parents=True, exist_ok=True)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        task_summary = task_description[:80].replace("\n", " ")

        workers = registry.all_workers()
        sub_managers = [n for n in registry.all_managers() if n.title != "Task Force Lead"]

        team_members = [n.title for n in sub_managers] + [n.title for n in workers]
        team_str = "Task Force Lead → " + ", ".join(team_members) if team_members else "Task Force Lead (solo)"

        done_workers = sum(1 for n in workers if n.status == _AgentStatus.DONE)
        fail_workers = sum(1 for n in workers if n.status == _AgentStatus.FAILED)
        total_workers = len(workers)

        if report.status == _TaskStatus.DONE:
            outcome = "DONE" if fail_workers == 0 else f"PARTIAL ({done_workers}/{total_workers} workers succeeded)"
        else:
            outcome = f"FAILED ({done_workers}/{total_workers} workers succeeded)"

        entry = (
            f"\n## {today} — {task_summary}\n"
            f"- Team: {team_str}\n"
            f"- Outcome: {outcome}\n"
            f"- Tokens: {tokens_total:,}\n"
        )

        is_new = not history_file.exists() or history_file.stat().st_size == 0
        with history_file.open("a", encoding="utf-8") as f:
            if is_new:
                f.write("# Company Task History\n")
            f.write(entry)
    except Exception:
        pass  # History log is non-critical


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

    # Load company knowledge base + task history — both injected into the task force lead.
    from pathlib import Path as _Path
    _kb_path = _Path(workspace_root) / "shared" / "_company_knowledge.md"
    _company_kb = ""
    if _kb_path.exists():
        try:
            _kb_content = _kb_path.read_text(encoding="utf-8").strip()
            if _kb_content:
                _company_kb = f"\n\n## Company Knowledge Base\n{_kb_content[:3000]}"
        except OSError:
            pass

    _history_path = _Path(workspace_root) / "shared" / "_company_history.md"
    _company_history = ""
    if _history_path.exists():
        try:
            _history_content = _history_path.read_text(encoding="utf-8").strip()
            if _history_content:
                # Keep only the last 3000 chars (most recent entries)
                _company_history = f"\n\n## Company Task History\n{_history_content[-3000:]}"
        except OSError:
            pass

    base_tools = ["file_list", "file_read", "file_write", "file_delete", "propose_external_action", "shell_exec"]
    if settings.has_web_search:
        base_tools.insert(0, "web_search")

    config = AgentConfig(
        role=AgentRole.MANAGER,
        title="Task Force Lead",
        allowed_tools=base_tools,
        mission=(
            f"You are a task force lead for **{company.name}**.\n"
            f"Company vision: {company.vision}\n"
            + _company_kb
            + _company_history
            + f"\n\nOfficial workspace folders:\n{official_folders_str}\n"
            "Any folder NOT in this list is a rogue artifact and must be deleted during cleanup.\n\n"
            f"Your task: {task_description}\n\n"
            "Before designing your team:\n"
            "1. Use `file_list` on the workspace root to check what exists — identify rogue folders "
            "and build on existing work, do not redo it.\n"
            "2. If the task involves a Next.js project, read its AGENTS.md first with `file_read`. "
            "For example, the Momentum Next.js guide is at "
            "'marketing-produit-et-aide-la-vente/momentum-nextjs/AGENTS.md'. "
            "That file contains critical patterns (Button API, Tailwind v4, Framer Motion, "
            "design system, content integrity rules). Workers must follow it exactly. "
            "Pass the relevant sections as context when you assign their missions.\n\n"
            "## Tool allocation rules for your team\n"
            + (
                "- You have `web_search` — use it before making any factual claims about the market, "
                "competitors, or external data. Assign it to workers that need external research.\n"
                if settings.has_web_search else
                "- web_search is not configured. Workers cannot search the web — base decisions on "
                "provided context and general knowledge; flag gaps clearly.\n"
            )
            + "- Assign `shell_exec` to workers that need to run system commands: scaffold a real "
            "Next.js app ('bun create next-app@latest my-app --yes'), install deps ('bun install'), "
            "build ('bun run build'), process media with ffmpeg, or run any script. "
            "Always use shell_exec for project scaffolding — NEVER write package.json / node_modules "
            "by hand. cwd is relative to workspace root (e.g. 'croissance-strat-gie/my-site').\n"
            "- **Next.js / Turbopack error handling — mandatory for all frontend workers**: "
            "After writing any Next.js code, ALWAYS run `bun run build` (not just `bun run dev`). "
            "Build output contains all TypeScript and Turbopack errors with exact file paths and line numbers. "
            "Read every error, fix each file with file_write, then run build again — repeat until build exits 0. "
            "NEVER report a Next.js project as done if `bun run build` has not exited successfully. "
            "Common issues to watch for: "
            "(1) This project uses shadcn with @base-ui/react — Button does NOT support 'asChild'. "
            "Use 'buttonVariants' + 'Link' pattern: "
            "import { buttonVariants } from '@/components/ui/button'; "
            "<Link href='...' className={cn(buttonVariants({ variant, size }), 'extra-classes'}>text</Link>. "
            "(2) JSX apostrophes: use actual ' or &apos; — never HTML &apos; entities inside JSX text. "
            "(3) Tailwind v4: globals.css uses '@import tailwindcss' — do NOT change or add @tailwind directives. "
            "Use only shadcn CSS variables: bg-background, bg-card, bg-muted, bg-primary, "
            "text-foreground, text-muted-foreground, border-border. "
            "(4) Add shadcn components via CLI only: `bunx shadcn@latest add <component> -y`. "
            "Never copy-paste component code by hand.\n"
            "- **Launch instructions — mandatory**: whenever a worker delivers a runnable project "
            "(Next.js, React, Vite, Python app, etc.), the worker's report MUST end with a "
            "'## How to run' section containing the exact shell commands to start it locally "
            "(e.g. `cd marketing-produit-et-aide-la-vente/momentum-nextjs && bun run dev`). "
            "Path must be workspace-relative. Your synthesis report must relay this section "
            "verbatim — the founder needs to copy-paste those commands.\n"
            "- Assign `propose_external_action` to any worker that needs to propose a real-world "
            "action (email, LinkedIn post, social media, outreach). That tool logs the action for "
            "founder approval — it does NOT execute it immediately.\n"
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

    # Load custom token budgets from Layer 5 (Gap 3 fix).
    budget_overrides: dict[str, int] = {}
    async with get_session() as db:
        ca_repo = CompanyAgentRepository(db)
        for ca in await ca_repo.list_active(company.id):
            if ca.token_budget > 0:
                budget_overrides[ca.title] = ca.token_budget

    spawner = Spawner(
        session_id=session.id,
        company_name=company.name,
        company_pitch=company.pitch,
        registry=registry,
        bus=bus,
        budget_manager=budget_manager,
        workspace_root=workspace_root,
        root_workspace_access=True,  # task force workers act on CEO authority
        on_progress=on_status,
        budget_overrides=budget_overrides,
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

    # Layer 5: Record persistent agent identities + task performance.
    from dri.core.models import AgentStatus as _AgentStatus
    all_nodes = list(registry.snapshot().nodes.values())
    tokens_total = sum(n.tokens_used for n in all_nodes)

    async with get_session() as db:
        ca_repo = CompanyAgentRepository(db)
        for node in all_nodes:
            ca = await ca_repo.get_or_create(
                company_id=company.id,
                title=node.title,
                role=node.role.value,
                dept_slug=_company_slug(node.title),
            )
            await ca_repo.record_task(ca.id, success=(node.status == _AgentStatus.DONE))

    # Layer 6: Append an entry to the company task history log.
    _append_company_history(
        workspace_root=workspace_root,
        task_description=task_description,
        registry=registry,
        report=report,
        tokens_total=tokens_total,
    )

    async with get_session() as db:
        session_repo = SessionRepository(db)
        await session_repo.complete(session.id)

    return report.result or "[Task force produced no result]"
