# DRI Multi-Agent Architecture — CLAUDE.md

> **For any new agent taking over this project:** This file is your single source of truth.
> Read it **entirely** before touching any code. It reflects the exact state of the codebase
> as of 2026-05-01. Never start from zero — everything is here.

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
│       ├── connectors/
│       │   ├── __init__.py               ← imports all connectors (self-registration)
│       │   ├── base.py                   ← BaseConnector ABC + ConnectorResult dataclass
│       │   ├── registry.py               ← ConnectorRegistry.get_for(action_type, action)
│       │   ├── email_smtp.py             ← SMTP email connector (stdlib only)
│       │   └── webhook.py                ← HTTP POST (Slack/Discord/Make.com/Zapier/n8n)
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
│   ├── _knowledge/                ← PERSISTENT: agent adaptive memory, never deleted
│   │   ├── chief-marketing-officer/
│   │   │   ├── expertise.md       ← manager's accumulated domain knowledge
│   │   │   └── feedback.md        ← feedback written by CEO/parent
│   │   └── seo-specialist/
│   │       ├── expertise.md       ← worker's accumulated domain knowledge
│   │       └── feedback.md        ← feedback written by manager after task review
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

### `_knowledge/` adaptive memory

`_knowledge/<title-slug>/` persists indefinitely — it is **never** touched by `_cleanup_wip()`.

- **expertise.md** — written by the agent itself (via `file_write`) at the end of each task.
  Contains: patterns that worked, pitfalls to avoid, domain insights.
- **feedback.md** — written by the parent manager after evaluating the worker's output.
  Contains: what was done well, concrete improvements, domain rules.

Before each task, `BaseAgent.run()` loads these files via `AgentMemory.for_agent()` and
injects them as `ContextPacket.agent_memory` → the `## Your Persistent Memory` section
of the system prompt. The agent cannot ignore it — it's in the system prompt, not a file to read.

`_knowledge/` is excluded from `_inventory_dept_files()` so it never appears in agent reports.

---

## Tools System

All tools registered in `ToolRegistry` at import time via `dri/tools/__init__.py`.

| Tool | Description | Notes |
|---|---|---|
| `web_search` | Search the web | Requires TAVILY_API_KEY or BRAVE_API_KEY |
| `code_exec` | Execute Python in sandboxed subprocess | |
| `shell_exec` | Run system commands within the workspace | Allowlist: bun, bunx, npx, npm, node, uv, python, python3, ffmpeg, ffprobe, git, magick, convert. CWD always inside workspace. No `shell=True`. Timeout max 300s. |
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
- `CompanyMessage`: id, company_id, role (user/ceo/summary), content

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

## Memory Architecture — Complete System (as of 2026-04-29)

The system has 4 active memory layers plus 2 planned layers:

```
Layer 4 (ACTIVE): CEO Conversation Summarization
  When > 40 non-summary messages, compress oldest → single summary record in DB.
  Role "summary" in company_messages. Built by _maybe_summarize_ceo_history().
  _build_ceo_messages() prepends summary to first user message in window.
  Cycle: 40 msgs → summarize → keep 14 verbatim → accumulate 26 more → repeat.

Layer 3 (ACTIVE): Company Knowledge Base
  File: shared/_company_knowledge.md
  Written by: CEO-spawned team after major decisions / milestones.
  Read by: every task force lead (injected into mission at task start).
  Sections: ## Strategic Decisions / ## Brand & Voice / ## Technical Stack /
            ## Completed Milestones / ## Lessons Learned
  This is the institutional long-term memory shared across all agents.

Layer 2 (ACTIVE): Role Persistent Memory
  Location: <dept>/_knowledge/<title-slug>/
  Files: expertise.md (self-written by agent) + feedback.md (written by manager).
  Read by: BaseAgent.run() before each task → injected in ContextPacket.agent_memory
           → "## Your Persistent Memory" section in system prompt.
  Written by: worker via file_write at end of task (task prompt instruction).
             manager via file_write after synthesis (feedback to each worker).
  Never cleaned by _cleanup_wip(). Excluded from inventory + workspace snapshot.

Layer 1 (ACTIVE): Active Context Pruning
  Agentic loop: _MAX_HISTORY_ROUNDS = 12 (last 12 tool-call rounds kept).
  CEO chat: 14 verbatim messages + optional summary prefix.

Layer 0 (ACTIVE): DB Persistence (metadata only)
  company_messages: full CEO conversation history (with summary records).
  agents / tasks / tool_calls: operational metadata per session.

Layer 5 (ACTIVE): Persistent Agent Identities
  Table: company_agents (id, company_id, title, role, dept_slug, task_count, success_count,
         token_budget, notes, status, created_at, last_active_at)
  Written by: _run_task_force() after every task force — all registry nodes recorded.
  CLI: dri company team list / show / note / remove / promote
  Enables: performance tracking, success rate, custom budget, soft-delete.
  Note: token_budget stored but not yet applied at spawn time (future iteration).

Layer 6 (ACTIVE): Company Task History
  File: shared/_company_history.md
  Append-only log: date, task summary, team, outcome, tokens used.
  Written by: _append_company_history() in company_executor.py after every task force.
  Read by: task force lead (injected in mission as "## Company Task History", last 3000 chars).
```

---

## Current Implementation State (as of 2026-04-30)

### Completed
- [x] CLAUDE.md
- [x] pyproject.toml
- [x] .env.example — includes connector settings (SMTP, webhook docs)
- [x] src/dri/config/settings.py — SMTP settings added (smtp_host/port/user/password/from)
- [x] src/dri/core/models.py — includes CompanyAgent (Layer 5)
- [x] src/dri/core/registry.py
- [x] src/dri/core/memory.py — ContextPacket + AgentMemory (layer 2 persistent memory) + agent_memory field
- [x] src/dri/core/budget.py
- [x] src/dri/core/communication.py
- [x] src/dri/storage/database.py
- [x] src/dri/storage/orm.py — includes CompanyAgentORM (Layer 5)
- [x] src/dri/storage/repositories.py — includes CompanyAgentRepository (Layer 5), `remove_department`, `replace_with_summary`
- [x] src/dri/skills/base.py + catalog.py + registry.py
- [x] src/dri/tools/base.py + __init__.py
- [x] src/dri/tools/web_search.py
- [x] src/dri/tools/code_exec.py
- [x] src/dri/tools/file_ops.py — file_read / file_write / file_list / file_delete + RBAC. File handle uses context manager. Delete counter is per-agent-per-folder (keyed by `_agent_id`).
- [x] src/dri/tools/external_actions.py — propose_external_action + enum validation + content check. action_id is now UUID string (no race condition).
- [x] src/dri/tools/shell_exec.py — shell_exec tool: allowlisted executables (bun/uv/ffmpeg/git/node/…), CWD sandboxed to workspace, no shell=True, 300s max timeout, 20k char output cap. **Git destructive subcommand guard**: `git clean`, `git rm`, `git restore`, `git reset --hard/--mixed`, `git checkout -- <file>` are blocked at the tool level — agents must use `propose_external_action` with `bulk_file_delete` for any workspace-destroying operation.
- [x] src/dri/agents/base.py — _cleanup_wip / _inventory_dept_files / _fail_report. Persistent memory: _load_agent_memory() + _knowledge_path_str(). Memory loaded before each task into ContextPacket.agent_memory.
- [x] src/dri/agents/root.py — fixed __import__ → proper top-level imports
- [x] src/dri/agents/manager.py — synthesis uses agentic loop. Writes targeted feedback to each worker's _knowledge/feedback.md after synthesis.
- [x] src/dri/agents/worker.py — knowledge update instruction: writes expertise.md at end of each task.
- [x] src/dri/orchestration/spawner.py — RBAC permissions, auto-include file tools
- [x] src/dri/orchestration/executor.py
- [x] src/dri/orchestration/company_executor.py — Layer 3 (company KB), Layer 4 (CEO summarization), Layer 5 (agent tracking via _run_task_force), Layer 6 (history log + injection). _append_company_history() writes shared/_company_history.md. **CEO conversation safety** (see section below).
- [x] src/dri/connectors/base.py — BaseConnector ABC + ConnectorResult
- [x] src/dri/connectors/registry.py — ConnectorRegistry (dedup on register)
- [x] src/dri/connectors/email_smtp.py — SMTP email (Gmail, Outlook, any SMTP)
- [x] src/dri/connectors/webhook.py — HTTP POST (Slack, Discord, Make.com, Zapier, n8n, custom)
- [x] src/dri/connectors/__init__.py
- [x] src/dri/api/cli.py — all commands + connector dispatch on approval + Windows UTF-8 fix. `dri company team list/show/note/remove/promote` (Layer 5 CLI).
- [x] tests/unit/ — 122/122 passing

### Connectors (all completed 2026-04-27)
- [x] Slack Bot Token — `src/dri/connectors/slack_bot.py`
- [x] Twilio SMS — `src/dri/connectors/twilio_sms.py`
- [x] SendGrid — `src/dri/connectors/sendgrid_email.py`
- [x] LinkedIn — `src/dri/connectors/linkedin.py`

### Memory system fixes (completed 2026-04-30)

- [x] **Layer 2 fix** — `memory_dept: str = ""` added to `ContextPacket`. `Spawner.spawn()` computes
  it from the agent title/parent title (managers → own slug, workers → parent slug). `AgentMemory.for_agent()`
  uses it as priority over permission scan. `_knowledge_path_str()` and `_load_agent_memory()` updated.
  5 new tests added → **106/106 passing**.

- [x] **Gap 2 fix** — `CompanyExecutor.chat()` now loads `shared/_company_history.md` and appends it to
  the CEO system prompt. CEO has full Layer 6 visibility in chat mode.

- [x] **Gap 3 fix** — `Spawner` accepts `budget_overrides: dict[str, int]`. `_run_task_force()` loads
  active `CompanyAgent` records and passes any `token_budget > 0` as overrides. Custom budgets set via
  `dri company team promote` are now applied at spawn time.

### UX & safety fixes (completed 2026-05-01)

- [x] **Git destructive command guard** — `shell_exec.py` now blocks `git clean`, `git rm`,
  `git restore`, `git reset --hard/--mixed`, `git checkout -- <file>` at the tool level.
  Any workspace-destroying operation must go through `propose_external_action` with
  `action_type='bulk_file_delete'` → requires founder approval.

- [x] **"Rogue artifact" instruction removed** — The task force lead's mission no longer tells
  agents to auto-delete unrecognized folders. Unknown folders are now mentioned in the synthesis
  report only, and any folder cleanup requires founder approval.

- [x] **CEO conversation-first behavior** — `_build_ceo_messages()` injects `[NEW CONVERSATION]`
  on the first ever message. The CEO system prompt now has three execution tiers:
  1. `[NEW CONVERSATION]` → greet + invite task, **do NOT spawn**.
  2. Major construction task (app, multi-dept) → send ONE confirmation message, spawn only after founder approval.
  3. Simple task (report, content, fix) → spawn immediately as before.

- [x] **CEO "explain before restart" rule** — New section in CEO system prompt: if the founder
  asks what happened / why something is missing, the CEO MUST explain from workspace + history
  before proposing next steps. Never silently restart.

- [x] **CEO live progress** — `on_status("CEO thinking... (round N)")` called every loop
  iteration, so the Live panel shows the CEO is active even between spawns.

- [x] **Spawn deduplication** — `_ceo_loop` tracks `_spawned_task_keys` (set of first-120-char
  normalized task descriptions). A second `spawn_team` call for the same task is blocked with
  a `[DUPLICATE SPAWN BLOCKED]` message instead of running a second team.

- [x] **Budget borrowing** — `BudgetManager.return_unused()` + `add_to_allocation()`. Wired in `manager.py`: unused tokens pooled from completed workers, redistributed to budget-exhausted workers before they are retried.
- [x] **GitHub connector** — `src/dri/connectors/github.py`. Handles `github_push`, `github_create_pr`, `github_create_repo` action types. Requires `GITHUB_TOKEN` in `.env`. Registered in `connectors/__init__.py`.
- [x] **Integration tests** — `tests/integration/test_company_workflow.py` + `test_persistent_company.py` + `test_full_session.py`. 186 pass + 3 skip (webhook test skips on HTTP 429 rate-limit).
- [x] **`dri company files`** — shows workspace file tree via Rich with dept filter and file sizes.
- [x] **`dri company delete`** — atomically removes DB record (company + messages + agents) and workspace folder. Supports `--archive` and `--force`.
- [x] **`dri company recover`** — scans for orphan workspaces and re-imports them. `dri company list` shows orphan warning.
- [x] **Production DB isolation** — test fixtures use explicit `:memory:` URL; `reload_settings` no longer clears the test DB override.
- [x] **GitHub connector E2E validated** — `github_create_repo` + `github_push` tested against `Multi-agents-Company` org (2026-05-03). Repo `agence-nextmoderne-docs` created + strategy doc pushed.
- [x] **`_inventory_shared_files()` Windows backslash fix** — used `str()` instead of `.as_posix()`, causing duplicate paths in synthesis reports (slash vs backslash). Fixed in `base.py`. Also harmonized `_INVENTORY_INFRA_FILES` constant across both inventory methods.
- [x] **`workspace/momentum/` orphan cleanup** — deleted (no DB record, no `shared/`, non-recoverable Next.js orphan).

---

## Notes for the Next Agent

- **Read the full file before touching anything. Especially the Memory Architecture section.**
- Active companies (as of 2026-05-03): **Agence NextModerne** and **Zenith**.
  `workspace/momentum/` has been deleted (orphan, no DB record, no `shared/`).
  Use `uv run dri company list` to confirm current state.
- **LangGraph is NOT used** despite being in the architecture table. `graph.py` is a skeleton.
  Don't add LangGraph code without user approval.
- `settings.py` singleton: `from dri.config.settings import settings` or `get_settings()`.
  Never read env vars directly elsewhere.
- All async: `async def` everywhere. No sync/async mixing without `asyncio.to_thread()`.
- Commit style: `feat: X`, `fix: Y`, `refactor: Z`. Separate logical concerns into separate commits.
- The `docs/` folder is gitignored (personal notes). Do not commit anything there.
- `_wip/` auto-deleted. `_knowledge/` never deleted. `shared/_company_knowledge.md` is institutional memory.
- **Memory layers in brief**: active context (base.py _MAX_HISTORY_ROUNDS=12) → role files (_knowledge/) → company KB (shared/_company_knowledge.md) → CEO history summary (company_messages role="summary"). See Memory Architecture section for full detail.
- **Connectors** (`src/dri/connectors/`): self-register at import. Pattern: `ConnectorRegistry.register(MyConnector())` at module bottom + import in `__init__.py`.
- **propose_external_action**: `content` must be the full text. `action_type` in `_VALID_TYPES`. Enum: `email`, `webhook`, `linkedin_message`, `social_post`, `sms`, `slack_message`, `phone_call`, `outreach_message`, `bulk_file_delete`, `github_push`, `github_create_pr`, `github_create_repo`, `other`.
- **Approval dispatch**: after founder approves, `cli.py` calls `ConnectorRegistry.get_for(action_type, action)` → executes.
- **Windows UTF-8**: `cli.py` sets `sys.stdout` to UTF-8 + `Console(legacy_windows=False)`.
- **Provider**: Gemini via Vertex AI. Workers = gemini-2.5-flash. CEO = gemini-2.5-pro.
- **Tests**: `uv run pytest tests/ -q` must stay at **186 passed / 3 skipped** before any commit. The webhook live test skips on HTTP 429 (external rate limit) — this is expected.
- **Slug normalization**: always use `_slug()` in `cli.py` or `_company_slug()` in `company_executor.py` — both use NFD normalization for French accents. Never use plain `re.sub(r'[^a-z0-9]+', '-', name.lower())` directly.

### Real-world test to run (requested by founder, 2026-05-01)

Run this end-to-end test from the user's perspective and document every friction point:

```bash
uv run dri company create --pitch "l'objectif de l'entreprise est de gérer un parc immobilier de 6 appartements au sein d'un immeuble. j'aimerai un site web public et privé pour prendre en charge la gestion de l'ensemble de ces bien. A savoir : la suivi des recettes et des dépenses ainsi que les recommandations d'optimisation financieres et fiscales."
uv run dri company chat
```

**What to evaluate from the user's perspective:**
1. Does the CEO greet the founder first and NOT immediately spawn a team? (Fix 3 validation)
2. When you ask it a question, does it answer instead of relaunching? (Fix 4 validation)
3. Is the Live progress panel showing meaningful status? (Fix 5 validation)
4. When you trigger a build task, does the CEO ask for confirmation before spawning? (Fix 3b)
5. Are `git clean` equivalents blocked if any agent tries them? (Fix 1 validation)
6. Is the workspace clean after task completion — no phantom files? (Fix 2 validation)
7. Report all UX friction: confusing messages, missing feedback, unclear states, unexpected behaviors.

**Known issues still open** (fix if time allows):
- Agents can still run `git push --force` (not blocked, needed for future GitHub connector)
- No structured progress bar (which agent % done) — only text status
- No `/status` CLI command to check what's running mid-task

**Deletion safety reminder**: agents can delete individual files with `file_delete`. For bulk
or folder-level deletion, they must use `propose_external_action(action_type='bulk_file_delete')`
which queues a founder-approval request visible via `dri company approvals list`.
