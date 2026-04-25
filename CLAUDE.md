# DRI Multi-Agent Architecture — CLAUDE.md

> **For any new agent taking over this project:** This file is your single source of truth.
> Read it **entirely** before touching any code. It reflects the exact state of the codebase
> as of 2026-04-26. Never start from zero — everything is here.

---

## Project Vision

A platform where a user pitches any business idea to a root AI agent (the CEO), and a full
hierarchical multi-agent "company" self-organizes from scratch. The system is general-purpose:
it can create and run any type of company, fully autonomously.

The user only ever speaks to the root agent (CEO). Everything else is handled by the hierarchy.

---

## Core Principles (DRI Model — Apple-inspired)

1. **Single responsibility**: every agent has exactly one role and one mission.
2. **Hierarchical isolation**: each agent only knows its parent (N+1) and its direct children (N-1).
3. **Parent owns children**: the parent creates, configures, monitors, and if necessary removes its children.
4. **Context injection**: the parent decides what context (skills, constraints, budget) to pass to each child — the child has no global awareness.
5. **No shortcuts**: functional correctness and security over speed of implementation.
6. **One change = one place**: no logic duplication, strict DRY, SOLID throughout.

---

## Architecture Decisions (all final, do not revisit without user approval)

| Decision | Choice | Reason |
|---|---|---|
| LLM provider | Anthropic Claude (claude-sonnet-4-6 default) | Best reasoning, tool use, caching |
| Orchestration | Pure asyncio + Spawner pattern | LangGraph was the original plan but **not implemented** — actual orchestration is asyncio-based (see Note below) |
| Async runtime | Python asyncio | True parallelism for concurrent agent branches |
| Persistence | SQLAlchemy 2.0 async + SQLite (swappable to PostgreSQL) | Lightweight local-first, production-ready path |
| Data validation | Pydantic v2 | Schema enforcement at all boundaries |
| CLI | Rich + Typer | Beautiful, professional terminal UI |
| Python version | 3.12+ | Latest stable, best asyncio support |
| Config | Pydantic Settings + .env | Twelve-factor app, user-configurable |
| Testing | pytest + pytest-asyncio | Standard, works with async |

> **Note on LangGraph:** `src/dri/orchestration/graph.py` exists as a skeleton but LangGraph
> is **not used** in the actual execution path. All orchestration is done via `Spawner` +
> `asyncio.gather`. Do not add LangGraph dependencies without discussing with the user first.

---

## Project Structure

```
Multi_Agent_DRI_Architecture/
├── CLAUDE.md                              ← YOU ARE HERE
├── pyproject.toml                         ← deps + project metadata
├── .env.example                           ← all configurable params
├── .env                                   ← user's local config (gitignored)
├── docs/                                  ← personal docs, gitignored
│   └── CLI/reference.md                  ← full CLI command reference
├── src/
│   └── dri/
│       ├── __init__.py
│       ├── config/
│       │   ├── __init__.py
│       │   └── settings.py               ← Pydantic Settings singleton
│       ├── core/
│       │   ├── __init__.py
│       │   ├── models.py                 ← ALL domain models (Pydantic)
│       │   ├── registry.py               ← Agent registry (org chart in memory + DB)
│       │   ├── memory.py                 ← ContextPacket builder + system prompt renderer
│       │   ├── budget.py                 ← Budget tracking + enforcement
│       │   └── communication.py          ← Message protocol (delegate / report / escalate)
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── database.py               ← SQLAlchemy async engine + session factory
│       │   ├── orm.py                    ← SQLAlchemy ORM models
│       │   └── repositories.py           ← Repository pattern (all DB access here)
│       ├── skills/
│       │   ├── __init__.py
│       │   ├── base.py                   ← Skill base class
│       │   ├── catalog.py                ← Built-in skill definitions
│       │   └── registry.py               ← Runtime skill registry per agent
│       ├── tools/
│       │   ├── __init__.py               ← imports all tools to trigger registration
│       │   ├── base.py                   ← BaseTool + ToolRegistry
│       │   ├── web_search.py             ← Web search (Tavily or Brave API)
│       │   ├── code_exec.py              ← Sandboxed Python execution
│       │   ├── file_ops.py               ← file_read / file_write / file_list / file_delete
│       │   └── external_actions.py       ← propose_external_action (approval system)
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── base.py                   ← BaseAgent: lifecycle, LLM, tools, interruption handling
│       │   ├── root.py                   ← RootAgent (CEO): user interface + org design
│       │   ├── manager.py                ← ManagerAgent: spawn/supervise/synthesize teams
│       │   └── worker.py                 ← WorkerAgent: leaf execution with tools
│       ├── orchestration/
│       │   ├── __init__.py
│       │   ├── graph.py                  ← LangGraph skeleton (NOT used in execution path)
│       │   ├── spawner.py                ← Agent spawn + RBAC permission assignment
│       │   ├── executor.py               ← One-shot session bootstrap
│       │   └── company_executor.py       ← Persistent company: create / chat / task
│       └── api/
│           ├── __init__.py
│           └── cli.py                    ← Rich CLI — all user-facing commands
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── unit/
    │   └── __init__.py
    └── integration/
        └── __init__.py
```

---

## Data Flow

```
User input
    │
    ▼
CompanyExecutor.chat()          ← persistent mode (main mode)
    │
    ▼
CEO agentic loop
    │   Strategic discussion → responds directly
    │   Execution task → calls spawn_team tool
    │
    ▼
Executor.run(pitch, workspace_root)
    │
    ▼
RootAgent (task-force CEO)
    │   designs org → calls design_company tool
    │
    ├──[parallel]──► ManagerAgent (CMO)
    │                    │ plans team → calls create_org_plan tool
    │                    ├──[parallel]──► WorkerAgent (SEO Specialist)
    │                    └──[parallel]──► WorkerAgent (Content Writer)
    │
    └──[parallel]──► ManagerAgent (CTO)
                         ├──[parallel]──► WorkerAgent (Backend Dev)
                         └──[parallel]──► WorkerAgent (Data Engineer)

Results bubble up:
    worker._fail_report() or result → manager synthesizes → CEO synthesizes → User

On interruption (timeout / budget / exception):
    _cleanup_wip() → _inventory_dept_files() → structured _fail_report() → N+1
```

---

## Workspace & RBAC System

Each persistent company has an isolated workspace at `workspace/<company-slug>/`.

### Directory convention

```
workspace/momentum/
├── shared/                        ← cross-team deliverables + pending approvals
│   ├── _pending_approvals.json    ← external action queue (managed by approval system)
│   └── archive/                   ← decommissioned dept deliverables
│       └── chief-marketing-officer/
├── chief-marketing-officer/
│   ├── _wip/                      ← EPHEMERAL: deleted by framework after every task
│   └── strategy.md                ← deliverable: persists
├── chief-technology-officer/
│   └── ...
└── ...
```

### RBAC permissions (enforced by `file_ops.py` + `spawner.py`)

| Role | Own dept folder | `shared/` | Other depts |
|------|----------------|-----------|-------------|
| ROOT | R + W + D | R + W + D | R + W + D |
| MANAGER | R + W + D | R + W + D | Read only |
| WORKER | R + W + D | R + W + D | Read only |

### `_wip/` hard guarantee

`BaseAgent._cleanup_wip()` is called by the **framework** (not the LLM) after every task
completion or failure, before `_fail_report()`. This is unconditional — the LLM cannot
skip or forget it. `_wip/` files never survive a task boundary.

---

## Tools System

All tools registered in `ToolRegistry` at import time via `dri/tools/__init__.py`.

| Tool | Description | Notes |
|---|---|---|
| `web_search` | Search the web | Requires TAVILY_API_KEY or BRAVE_API_KEY |
| `code_exec` | Execute Python in sandboxed subprocess | |
| `file_read` | Read a file from workspace | RBAC enforced |
| `file_write` | Write/overwrite/append a file | RBAC enforced, creates parent dirs |
| `file_list` | List files in a directory | RBAC enforced |
| `file_delete` | Delete a single file | RBAC enforced |
| `propose_external_action` | Queue a real-world action for founder approval | Does NOT execute — writes to `shared/_pending_approvals.json` |

Tools are assigned to agents by their parent via `SpawnRequest.allowed_tools`.
Managers describe available tools in `_ORG_PLAN_TOOL` when planning their team.

---

## External Action Approval System

Agents **cannot** send emails, messages, or interact with the real world directly.
When such an action is needed, the agent calls `propose_external_action`:

1. Action is written to `shared/_pending_approvals.json` with full details (content,
   recipient, rationale, which agent proposed it, timestamp).
2. Agent reports upward: "Action #N pending founder approval."
3. Founder reviews and decides via CLI.

### CLI commands

```bash
dri company approvals list              # see pending actions
dri company approvals show <N>          # read full content + rationale
dri company approvals approve <N>       # approve (+ optional note)
dri company approvals reject <N>        # reject (+ optional reason)
```

---

## Agent Interruption Handling

When an agent fails (timeout / budget exceeded / exception):

1. `_cleanup_wip()` runs first — removes ephemeral files so inventory is clean.
2. `_inventory_dept_files()` lists all deliverable files currently on disk.
3. `_fail_report()` builds a structured report sent to N+1 containing:
   - Reason for interruption
   - List of files produced before interruption (kept on disk)
   - The incomplete task description
   - Three recommended actions: retry narrower / reassign remaining / escalate

The N+1 manager's synthesis prompt explicitly handles failure sub-reports —
it acknowledges the interruption, documents completed vs incomplete work,
and proposes a concrete next action.

---

## Agent System Prompt — Mandatory Rules

Every agent's system prompt (rendered by `ContextPacket.to_system_prompt()`) includes:

### Integrity Rules
- **Never fabricate** data, outcomes, or feedback. If you can't do something, say so.
- **Use `propose_external_action`** for any real-world interaction.
- **When you don't know something**, use `web_search` or escalate. Never invent.
- **Mark hypotheticals** as `[EXAMPLE — NOT REAL DATA]`.
- **Cite every file produced** in your report with its exact workspace-relative path.

### File Lifecycle Rules
- `<dept>/_wip/` → ephemeral working files. Delete before reporting done.
- `<dept>/` root and `shared/` → deliverables. Only save final output here.
- **Use `file_delete`** to remove obsolete files — never tell others to "ignore" a file.
- **Cite every deletion** in your report: path + reason.
- Do not delete files from another department's folder.

---

## Department Decommission

```bash
dri company decommission "Chief Marketing Officer"           # delete all
dri company decommission "Chief Marketing Officer" --archive # move deliverables to shared/archive/
dri company decommission "Chief Marketing Officer" --force   # skip confirmation
```

This command:
1. Lists all files in the dept folder (deliverables vs `_wip/`)
2. Archives or deletes based on `--archive` flag
3. Removes the department from `org_structure` in DB
4. Removes the dept folder

---

## Domain Models (src/dri/core/models.py)

Key types (all Pydantic v2):

- `AgentRole`: Enum — ROOT, MANAGER, WORKER
- `AgentStatus`: Enum — INITIALIZING, ACTIVE, WAITING, DONE, FAILED
- `AgentConfig`: id, role, title, mission, parent_id, depth, skills, allowed_tools, budget, model
- `AgentState`: mutable runtime state for an agent
- `Message` / `DelegateMessage` / `ReportMessage` / `EscalateMessage`: typed message envelopes
- `SpawnRequest`: what a parent sends to Spawner to create a child
- `WorkspacePermission`: path + can_read + can_write + can_delete
- `Skill`: name, description, instructions, required_tools
- `Task`: id, description, assigned_to, status, result
- `BudgetAllocation`: total, used, remaining per agent
- `PersistentCompany`: id, name, vision, pitch, org_structure, status
- `CompanyMessage`: id, company_id, role (user/ceo), content

---

## Key Invariants (never violate these)

1. **No agent accesses global state directly** — all state goes through the Repository layer.
2. **No lateral communication** — agents only talk to parent or children, never siblings.
3. **All LLM calls go through `BaseAgent._call_llm()`** — budget tracking, logging, caching.
4. **All DB access goes through repositories** — never use ORM models directly in business logic.
5. **All tool calls are async** — never block the event loop.
6. **Parent always outlives children** — cannot be DONE until all children are DONE or FAILED.
7. **Budget is always checked before LLM calls** — `BudgetManager.check_and_deduct()` in `_call_llm()`.
8. **`_cleanup_wip()` always runs** — called by framework in `run()` on success and failure alike.
9. **No agent invents data** — Integrity Rules are in every system prompt; violations are a bug.
10. **No real-world action without approval** — `propose_external_action` is the only path.

---

## CLI — Complete Command Reference

```bash
# One-shot session (no persistence)
uv run dri run
uv run dri run --pitch "My idea" --budget 500000

# Session history
uv run dri sessions

# Persistent company
uv run dri company create --pitch "My idea"
uv run dri company list
uv run dri company chat --id <ID>
uv run dri company task --task "Produce a market analysis report"
uv run dri company decommission "Chief Marketing Officer" --archive

# External action approvals
uv run dri company approvals list
uv run dri company approvals list --all          # include decided actions
uv run dri company approvals show <N>
uv run dri company approvals approve <N> --note "OK"
uv run dri company approvals reject <N> --note "Reformulate first"
```

Full reference: `docs/CLI/reference.md`

---

## Configuration (.env)

```
ANTHROPIC_API_KEY=your_key_here          # required
DEFAULT_MODEL=claude-sonnet-4-6
ROOT_MODEL=claude-sonnet-4-6
BUDGET_MAX_TOKENS_PER_SESSION=2000000
BUDGET_WARNING_THRESHOLD=0.2
BUDGET_CHILD_DEFAULT_SHARE=0.4
TAVILY_API_KEY=optional
BRAVE_API_KEY=optional
DATABASE_URL=sqlite+aiosqlite:///./dri_company.db
WORKSPACE_DIR=./workspace
MAX_CONCURRENT_AGENTS=20
MAX_SPAWN_DEPTH=10
AGENT_TIMEOUT_SECONDS=300
```

---

## How to Run

```bash
uv sync                  # install deps
uv sync --extra dev      # with test deps
cp .env.example .env     # configure (set ANTHROPIC_API_KEY at minimum)
uv run dri run           # one-shot mode
uv run dri company create && uv run dri company chat   # persistent mode
uv run pytest            # run tests
```

**Always use `uv`**, never `pip`.

---

## Current Implementation State (as of 2026-04-26)

### Completed
- [x] CLAUDE.md
- [x] pyproject.toml
- [x] .env.example
- [x] src/dri/config/settings.py
- [x] src/dri/core/models.py
- [x] src/dri/core/registry.py
- [x] src/dri/core/memory.py — ContextPacket + system prompt with integrity + file lifecycle rules
- [x] src/dri/core/budget.py
- [x] src/dri/core/communication.py
- [x] src/dri/storage/database.py
- [x] src/dri/storage/orm.py
- [x] src/dri/storage/repositories.py — includes `remove_department`
- [x] src/dri/skills/base.py + catalog.py + registry.py
- [x] src/dri/tools/base.py + __init__.py
- [x] src/dri/tools/web_search.py
- [x] src/dri/tools/code_exec.py
- [x] src/dri/tools/file_ops.py — file_read / file_write / file_list / file_delete + RBAC
- [x] src/dri/tools/external_actions.py — propose_external_action
- [x] src/dri/agents/base.py — _cleanup_wip / _inventory_dept_files / _fail_report enriched
- [x] src/dri/agents/root.py
- [x] src/dri/agents/manager.py — synthesis handles interruption reports
- [x] src/dri/agents/worker.py
- [x] src/dri/orchestration/spawner.py — RBAC permissions
- [x] src/dri/orchestration/executor.py
- [x] src/dri/orchestration/company_executor.py — persistent company mode
- [x] src/dri/api/cli.py — all commands including approvals + decommission
- [x] tests/unit/ (models, budget, memory, tools, registry)

### Pending
- [ ] tests/integration/ — full end-to-end pitch test (requires ANTHROPIC_API_KEY)
- [ ] Real execution of approved external actions (email/LinkedIn integrations)
- [ ] Next.js frontend (optional, post-MVP)

---

## Notes for the Next Agent

- **Read the full file before touching anything.**
- The active company for this project is **Momentum** (persistent company in DB).
  Workspace: `workspace/momentum/`. Use `uv run dri company list` to get the ID.
- **LangGraph is NOT used** despite being in the architecture table. `graph.py` is a skeleton.
  Don't add LangGraph code without user approval.
- `settings.py` singleton: `from dri.config.settings import settings` or `get_settings()`.
  Never read env vars directly elsewhere.
- All async: `async def` everywhere. No sync/async mixing without `asyncio.to_thread()`.
- Commit style: `feat: X`, `fix: Y`, `refactor: Z`. Separate logical concerns into separate commits.
- The `docs/` folder is gitignored (personal notes). Do not commit anything there.
- Workspace files in `shared/_pending_approvals.json` are the approval queue — do not modify manually.
- `_wip/` folders are auto-deleted by the framework — never rely on their contents persisting.
