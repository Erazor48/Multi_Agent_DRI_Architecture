"""
CompanyExecutor — manages persistent company lifecycle.

- create(pitch): designs the company, saves it to DB, returns PersistentCompany
- chat(company_id, message): sends a message to the persistent CEO, returns response
- task(company_id, task): spawns a full one-shot team to execute a task
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
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
    # Decompose accented chars (é→e, ç→c, etc.) before slugifying so French names work correctly
    normalized = unicodedata.normalize("NFD", name.lower())
    ascii_only = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")


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
    async def recover_scan() -> "list[_OrphanCandidate]":
        """Scan the workspace directory and return orphan company candidates."""
        return await _scan_orphan_workspaces()

    @staticmethod
    async def recover_import(folder_name: str, company_name: str) -> PersistentCompany:
        """
        Import an orphan workspace folder as a new PersistentCompany in the DB.
        Reads KB/history files to reconstruct a minimal pitch and org_structure.
        """
        workspace_path = settings.workspace_dir / folder_name
        shared = workspace_path / "shared"

        vision = ""
        kb = shared / "_company_knowledge.md"
        if kb.exists():
            try:
                content = kb.read_text(encoding="utf-8", errors="ignore")
                # Look for the Vision: line first, then fall back to first meaningful paragraph
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped.lower().startswith("vision:"):
                        vision = stripped[len("vision:"):].strip()[:300]
                        break
                if not vision:
                    # Use first heading content as vision (## Company Vision section)
                    in_vision = False
                    for line in content.splitlines():
                        if "vision" in line.lower() and line.startswith("#"):
                            in_vision = True
                            continue
                        if in_vision and line.strip() and not line.startswith("#"):
                            vision = line.strip()[:300]
                            break
            except OSError:
                pass
        if not vision:
            vision = f"Recovered workspace: {folder_name}"

        org_structure: list[dict[str, str]] = []
        reserved = {"shared", "ceo"}
        for entry in sorted(workspace_path.iterdir()):
            if entry.is_dir() and entry.name not in reserved and not entry.name.startswith("_"):
                title = re.sub(r"[-_]+", " ", entry.name).title()
                org_structure.append({"title": title, "mission": ""})

        company = PersistentCompany(
            name=company_name,
            vision=vision,
            pitch=vision,
            org_structure=org_structure,
        )
        await init_db()
        async with get_session() as db:
            repo = PersistentCompanyRepository(db)
            await repo.create(company)
        return company

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
            "- **New conversation rule**: if the founder's message is marked [NEW CONVERSATION], "
            "ALWAYS respond conversationally first: greet the founder, summarize the company "
            "structure in 2-3 sentences, and invite them to share their first task or ask questions. "
            "Do NOT call spawn_team on a [NEW CONVERSATION] message — wait for the founder to "
            "give you an explicit task before executing anything.\n"
            "- **Major task rule**: for large construction tasks (building an app, redesigning a "
            "full department, multi-team work), send ONE brief confirmation message first: "
            "outline your plan in 3-4 bullets and ask the founder to confirm. "
            "Only call spawn_team after the founder says 'go', 'proceed', 'yes', 'do it', or similar.\n"
            "- **Simple task rule**: for well-scoped tasks (a report, a content piece, a small fix), "
            "call spawn_team immediately — no confirmation needed.\n"
            "- For discussion and questions: respond directly without spawn_team.\n"
            "- Do NOT describe launching a team without actually calling the tool. "
            "'Je mandate une équipe' without a spawn_team call is fabrication and is strictly forbidden.\n"
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
            "- **Next.js / shadcn / Turbopack quality gate**: your workers MUST run `bun run build` "
            "after every frontend change and fix ALL errors before reporting done. "
            "A project with a failing build is NOT done — re-spawn with stricter instructions. "
            "Build output from Turbopack includes exact error locations; workers must read and fix every one.\n"
            "- **shadcn/ui commands** (for workers): always pass `--yes` to avoid interactive prompts:\n"
            "  - Init: `bunx shadcn@latest init --defaults --yes` (run once inside project dir)\n"
            "  - Add components: `bunx shadcn@latest add button card table --yes`\n"
            "- When a team delivers a runnable project, always surface the launch commands "
            "in your response using a code block — e.g. `cd <path> && bun run dev`. "
            "The founder must be able to copy-paste a single command to start the project.\n\n"

            "## Large task decomposition — mandatory for websites and multi-feature apps\n"
            "Building a website or complex application MUST be split across MULTIPLE sequential "
            "task forces — ONE task force per phase. Never try to build an entire website in a "
            "single spawn. The budget per worker is limited (~12 LLM rounds), so each task "
            "force must deliver one specific, testable milestone.\n\n"
            "Recommended phases for a web project:\n"
            "  Phase 1 — Scaffold & architecture: `bun create next-app`, install deps, "
            "directory structure, shadcn init, base layout, deploy config.\n"
            "  Phase 2 — Core pages: home, main landing, navigation, global styles.\n"
            "  Phase 3 — Feature pages: each major feature as its own task force.\n"
            "  Phase 4 — Backend/API: server actions, API routes, data layer.\n"
            "  Phase 5 — Polish & QA: responsive fixes, accessibility, final build check.\n\n"
            "Each task force MUST:\n"
            "  - Know exactly which files already exist (provided in task context from workspace snapshot).\n"
            "  - Build on what was done in previous phases — never re-scaffold from scratch.\n"
            "  - End with a passing `bun run build` before reporting done.\n\n"

            "## Workspace cleanup — strict scope\n"
            "When the founder asks to 'clean', 'fix', or 'tidy' the workspace:\n"
            "- This means: identify and fix SPECIFIC problems, preserve everything else.\n"
            "- It NEVER means: delete all files, wipe departments, or start from zero.\n"
            "- Rogue folders (not in the official list above) may be removed, but ONLY "
            "after using `file_list` to confirm they are truly empty or obsolete.\n"
            "- Deleting a folder with more than 3 files is blocked by the system — you "
            "must use `propose_external_action` with action_type='bulk_file_delete', "
            "listing every file with its rationale, and wait for founder approval.\n\n"

            "## When the founder asks what happened\n"
            "If the founder asks 'what happened', 'que s'est-il passé', 'why is X missing', "
            "'what did you do', 'explain', or any similar retrospective question:\n"
            "1. FIRST summarize what you observe in the workspace snapshot and what you know "
            "from the conversation history — tell the founder what was done, what succeeded, "
            "what failed, and what state the workspace is in.\n"
            "2. Only THEN propose next steps — and ask for confirmation before spawning.\n"
            "NEVER silently restart a phase or spawn a new team in response to a 'what happened' "
            "question — the founder needs an explanation, not more silent execution.\n\n"

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

    # Mark the first ever message so the CEO greets first instead of spawning immediately.
    final_content = current_user_message
    if not recent and not summaries:
        final_content = f"[NEW CONVERSATION — greet the founder first, do NOT spawn yet]\n\n{current_user_message}"

    llm_messages.append({"role": "user", "content": final_content})
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
    # Deduplication: track task descriptions that already have an active spawn this loop.
    _spawned_task_keys: set[str] = set()

    # Inject the real workspace state into the current user turn before the first LLM call.
    # This ensures the CEO always starts from ground truth — never from stale memory.
    _last_snapshot_hash: str = ""
    if msgs and msgs[-1].get("role") == "user":
        snapshot = _workspace_snapshot(workspace_root)
        _last_snapshot_hash = hashlib.md5(snapshot.encode()).hexdigest()
        original = msgs[-1]["content"]
        msgs[-1] = {
            **msgs[-1],
            "content": f"**Current workspace (verified on disk):**\n{snapshot}\n\n---\n\n{original}",
        }

    for round_idx in range(20):  # allow file inspection rounds before and between spawns
        on_status(f"CEO thinking... (round {round_idx + 1})")
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
                # Deduplication guard: prevent the CEO from spawning the same task twice
                # in the same loop (e.g. when it misremembers a prior spawn).
                task_key = task_desc[:120].lower().strip()
                if task_key in _spawned_task_keys:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_call_id": tc.id,
                        "tool_name": tc.name,
                        "content": (
                            "[DUPLICATE SPAWN BLOCKED] A team was already spawned for this task "
                            "in this conversation turn. Do not spawn again — wait for the previous "
                            "result or ask the founder what to do next."
                        ),
                    })
                    continue
                _spawned_task_keys.add(task_key)
                on_status(f"Spawning team: {task_desc}")
                result = await _run_task_force(
                    company=company,
                    task_description=task_desc,
                    workspace_root=workspace_root,
                    on_status=on_status,
                )
                # Append workspace snapshot only when its contents changed since last spawn —
                # avoids repeating 2000+ token snapshots for unchanged workspaces.
                new_snapshot = _workspace_snapshot(workspace_root)
                new_hash = hashlib.md5(new_snapshot.encode()).hexdigest()
                if new_hash != _last_snapshot_hash:
                    result += "\n\n---\n" + new_snapshot
                    _last_snapshot_hash = new_hash
                else:
                    result += "\n\n*(workspace unchanged since last spawn)*"
                tool_results.append({
                    "type": "tool_result",
                    "tool_call_id": tc.id,
                    "tool_name": tc.name,
                    "content": result,
                })

            elif tc.name in ("file_list", "file_read"):
                _path_label = (tc.input or {}).get("path", "")
                on_status(f"[CEO] {tc.name}" + (f": {_path_label}" if _path_label else ""))
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


_SNAPSHOT_MAX_FILES = 120  # cap file listing to keep CEO context budget under control


def _workspace_snapshot(workspace_root: str) -> str:
    """
    Return a verified listing of every deliverable file currently on disk.
    Injected after every spawn_team result so the CEO never cites phantom files.
    Capped at _SNAPSHOT_MAX_FILES lines to avoid blowing the context budget on large projects.
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
    truncated = len(files) > _SNAPSHOT_MAX_FILES
    for p in files[:_SNAPSHOT_MAX_FILES]:
        lines.append(f"  - {p}")
    if truncated:
        lines.append(f"  ... and {len(files) - _SNAPSHOT_MAX_FILES} more files (use file_list to explore)")
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
        _task_clean = task_description.replace("\n", " ")
        task_summary = (_task_clean[:100] + "…") if len(_task_clean) > 100 else _task_clean

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


async def _update_company_kb(
    *,
    workspace_root: str,
    company: PersistentCompany,
    task_description: str,
    task_result: str,
) -> None:
    """
    Rewrite shared/_company_knowledge.md to reflect decisions and learnings from the
    latest task. Called automatically after every successful task force (Layer 3).
    """
    from pathlib import Path as _Path
    kb_path = _Path(workspace_root) / "shared" / "_company_knowledge.md"
    existing = kb_path.read_text(encoding="utf-8").strip() if kb_path.exists() else ""

    provider = create_provider()
    response = await provider.call(
        system="You maintain a company knowledge base. Be concise and factual.",
        messages=[{
            "role": "user",
            "content": (
                f"Company: {company.name}\nVision: {company.vision}\n\n"
                + (f"## Current KB\n{existing[:3000]}\n\n" if existing else "")
                + f"## Task just completed\n{task_description[:200]}\n\n"
                + f"## Result summary\n{task_result[:1000]}\n\n"
                "Update the knowledge base to reflect what was learned or decided.\n"
                "Keep these sections (add if missing): "
                "## Strategic Decisions / ## Brand & Voice / ## Technical Stack / "
                "## Completed Milestones / ## Lessons Learned\n"
                "Max 200 lines total. Write the full updated file."
            ),
        }],
        tools=None,
        model=settings.default_model,
        max_tokens=4096,
    )
    if response.text:
        kb_path.write_text(response.text, encoding="utf-8")


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
        TaskStatus,
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

    # Load company knowledge base + task history.
    # _company_kb / _company_history: formatted strings (with section headings) for the TFL mission.
    # _company_kb_raw / _company_history_raw: raw content passed to Spawner → all child agents.
    from pathlib import Path as _Path
    _kb_path = _Path(workspace_root) / "shared" / "_company_knowledge.md"
    _company_kb_raw = ""
    _company_kb = ""
    if _kb_path.exists():
        try:
            _kb_content = _kb_path.read_text(encoding="utf-8").strip()
            if _kb_content:
                _company_kb_raw = _kb_content[:3000]
                _company_kb = f"\n\n## Company Knowledge Base\n{_company_kb_raw}"
        except OSError:
            pass

    _history_path = _Path(workspace_root) / "shared" / "_company_history.md"
    _company_history_raw = ""
    _company_history = ""
    if _history_path.exists():
        try:
            _history_content = _history_path.read_text(encoding="utf-8").strip()
            if _history_content:
                _company_history_raw = _history_content[-3000:]
                _company_history = f"\n\n## Company Task History\n{_company_history_raw}"
        except OSError:
            pass

    base_tools = ["file_list", "file_read", "file_write", "file_delete", "propose_external_action", "shell_exec", "tts_generate"]
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
            "If you find a folder NOT in this list, mention it in your synthesis report — "
            "do NOT delete it autonomously. Any cleanup of unrecognized folders requires "
            "founder approval via `propose_external_action` with action_type='bulk_file_delete', "
            "listing every file with its rationale.\n\n"
            f"Your task: {task_description}\n\n"
            "Before designing your team:\n"
            "1. Use `file_list` on the workspace root to check what exists — identify existing work "
            "and build on it, do not redo it.\n"
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
            "social_post, phone_call, outreach_message, bulk_file_delete, "
            "github_push, github_create_pr, github_create_repo, "
            "youtube_upload, youtube_create_playlist, other. Never invent a new type.\n"
            "- Use 'email' when recipient is an email address.\n"
            "- Use 'slack_message' when posting to a Slack channel or user "
            "(recipient = #channel-name, channel ID like C12345, or user ID like U12345). "
            "This is the preferred type for Slack — do NOT use 'webhook' for Slack channels.\n"
            "- Use 'sms' when recipient is a phone number in E.164 format (+33XXXXXXXXX).\n"
            "- Use 'webhook' when recipient is an HTTP/HTTPS URL (Make.com/Zapier/Discord/custom). "
            "The system will POST the content immediately on approval.\n"
            "- Use 'youtube_upload' to upload a video file to YouTube "
            "(recipient=channel_id_or_default, subject=video_title, content=description, "
            "file_path=workspace-relative path to the .mp4 file e.g. 'shared/video.mp4'). "
            "Video is uploaded as PRIVATE by default — founder controls visibility.\n"
            "- Use 'youtube_create_playlist' to create a new YouTube playlist "
            "(subject=playlist_title, content=description).\n"
            "- content MUST be the FULL TEXT of the message — not a reference to a file. "
            "If you saved a draft to a file, read it back with file_read and paste the entire text "
            "into content before calling propose_external_action.\n"
            "- recipient MUST be specific: an email address, a webhook URL, or a platform handle.\n\n"
            "## Deliverable placement — mandatory instruction to every worker\n"
            "When writing each worker's mission, you MUST include this rule verbatim:\n"
            "  'Save ALL final deliverables to `shared/`. Use your dept `_wip/` folder only for "
            "intermediate drafts — never for final output. Only deviate from `shared/` if this "
            "specific task explicitly requests dept-specific output.'\n"
            "A worker that saves a final file to its dept root instead of `shared/` has violated "
            "this rule. Note the violation in your synthesis report and propose moving the file.\n\n"
            "## Structured mission format — required for every worker\n"
            "Each worker mission you write MUST follow this structure:\n"
            "  1. **Role + context** — who they are and what they need to know\n"
            "  2. **Exact task** — what to produce (be specific)\n"
            "  3. **Deliverable path** — 'Save the final result to `shared/<specific-filename.ext>`'\n"
            "  4. **Done criteria** — 3-5 bullet points defining a complete, quality deliverable\n"
            "  5. **Do NOT redo** — list any existing files they must read and build upon\n"
            "Missions without a deliverable path or done criteria will produce ambiguous output."
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
        company_kb=_company_kb_raw,
        company_history_snippet=_company_history_raw,
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

    snapshot = _workspace_snapshot(workspace_root)
    task = Task(
        description=task_description,
        context=(
            f"Company: {company.name}\nVision: {company.vision}\n\n"
            f"**Current workspace (verified on disk):**\n{snapshot}"
        ),
        assigned_to=config.id,
        delegated_by="ceo",
    )

    async with get_session() as db:
        task_repo = TaskRepository(db)
        await task_repo.create(session.id, task)

    on_status(f"Task force active: {task_description}")
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

    # Layer 3: Auto-update company knowledge base after every successful task.
    if report.status == TaskStatus.DONE:
        try:
            await _update_company_kb(
                workspace_root=workspace_root,
                company=company,
                task_description=task_description,
                task_result=report.result or "",
            )
        except Exception:
            pass  # non-critical

    async with get_session() as db:
        session_repo = SessionRepository(db)
        await session_repo.complete(session.id)

    return report.result or "[Task force produced no result]"


class _OrphanCandidate:
    """A workspace folder that has no corresponding DB record."""
    def __init__(self, folder_name: str, inferred_name: str, workspace_path: str) -> None:
        self.folder_name = folder_name
        self.inferred_name = inferred_name
        self.workspace_path = workspace_path


async def _scan_orphan_workspaces() -> list[_OrphanCandidate]:
    """
    Find workspace directories that have no matching PersistentCompany in DB.
    A valid company workspace is a folder that contains a 'shared/' subdirectory.
    """
    from pathlib import Path as _Path
    import re as _re

    workspace_root = settings.workspace_dir
    if not workspace_root.exists():
        return []

    await init_db()

    # Collect all known company slugs from DB
    async with get_session() as db:
        repo = PersistentCompanyRepository(db)
        companies = await repo.list_active()

    known_slugs: set[str] = set()
    for c in companies:
        known_slugs.add(_company_slug(c.name))

    orphans: list[_OrphanCandidate] = []
    for entry in sorted(workspace_root.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / "shared").is_dir():
            continue  # Not a company workspace
        if entry.name in known_slugs:
            continue  # Already in DB

        # Try to infer a human-readable name from the KB or history files
        inferred = _infer_company_name(entry)
        orphans.append(_OrphanCandidate(
            folder_name=entry.name,
            inferred_name=inferred,
            workspace_path=str(entry),
        ))

    return orphans


def _infer_company_name(workspace_path: "Path") -> str:  # type: ignore[name-defined]
    """Try to extract the company name from its workspace files, falling back to folder name."""
    from pathlib import Path as _Path

    path = _Path(workspace_path)

    _SKIP_PREFIXES = ("company:", "nom:", "name:", "entreprise:", "vision:", "```", "---", "*", ">")

    _DOC_SUFFIXES = (" knowledge base", " - knowledge base", " kb", " base de connaissances")

    def _clean_line(raw: str) -> str:
        """Strip heading markers, code fences, known label prefixes, and doc suffixes."""
        line = raw.lstrip("#").strip()
        if line.startswith("```"):
            return ""
        for prefix in ("Company:", "Nom:", "Name:", "Entreprise:", "Vision:"):
            if line.lower().startswith(prefix.lower()):
                line = line[len(prefix):].strip()
                break
        # Strip generic document-title suffixes (e.g. "Zenith Knowledge Base" → "Zenith")
        lower = line.lower()
        for suffix in _DOC_SUFFIXES:
            if lower.endswith(suffix):
                line = line[: -len(suffix)].strip()
                break
        return line

    # Try _company_knowledge.md — scan lines until we find a non-empty, non-noise name
    kb = path / "shared" / "_company_knowledge.md"
    if kb.exists():
        try:
            for raw in kb.read_text(encoding="utf-8", errors="ignore").splitlines():
                name = _clean_line(raw)
                if name and not any(name.lower().startswith(p) for p in _SKIP_PREFIXES):
                    return name
        except OSError:
            pass

    # Try _company_history.md
    hist = path / "shared" / "_company_history.md"
    if hist.exists():
        try:
            for raw in hist.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw.strip()
                if line and not line.startswith("#") and not line.startswith("```"):
                    return line[:60]
        except OSError:
            pass

    # Fall back to humanizing the folder slug
    import re as _re
    return _re.sub(r"[-_]+", " ", path.name).title()


