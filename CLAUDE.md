# DRI Multi-Agent Architecture — CLAUDE.md

> **For any new agent taking over this project:** This file is your single source of truth.
> Read it entirely before touching any code. It contains the full vision, all decisions made,
> current state, and next steps. Never start from zero.

---

## Project Vision

A platform where a user pitches any business idea to a root AI agent (the CEO), and a full
hierarchical multi-agent "company" self-organizes from scratch. The system is general-purpose:
it can create and run any type of company, fully autonomously.

The user only ever speaks to the root agent. Everything else is handled by the agent hierarchy.

---

## Core Principles (DRI Model — Apple-inspired)

1. **Single responsibility**: every agent has exactly one role and one mission.
2. **Hierarchical isolation**: each agent only knows its parent (N+1) and its direct children (N-1).
3. **Parent owns children**: the parent creates, configures, monitors, and if necessary removes its children.
4. **Context injection**: the parent decides what context (skills, constraints, budget) to pass to each child — the child has no global awareness.
5. **No shortcuts**: functional correctness and security over speed of implementation.
6. **One change = one place**: no logic duplication, strict DRY, SOLID principles throughout.

---

## Architecture Decisions (all final, do not revisit without user approval)

| Decision | Choice | Reason |
|---|---|---|
| LLM provider | Anthropic Claude (claude-sonnet-4-6 default) | Best reasoning, tool use, caching |
| Orchestration | LangGraph | State management, Send API for parallelism, checkpointing |
| Async runtime | Python asyncio | True parallelism for concurrent agent branches |
| Persistence | SQLAlchemy 2.0 async + SQLite (swappable to PostgreSQL) | Lightweight local-first, production-ready path |
| Data validation | Pydantic v2 | Schema enforcement at all boundaries |
| CLI | Rich | Beautiful, professional terminal UI |
| Python version | 3.12+ | Latest stable, best asyncio support |
| Config | Pydantic Settings + .env | Twelve-factor app, user-configurable |
| Testing | pytest + pytest-asyncio | Standard, works with async |

---

## Project Structure

```
Multi_Agent_DRI_Architecture/
├── CLAUDE.md                        ← YOU ARE HERE
├── pyproject.toml                   ← deps + project metadata
├── .env.example                     ← all configurable params
├── .env                             ← user's local config (gitignored)
├── src/
│   └── dri/
│       ├── __init__.py
│       ├── config/
│       │   ├── __init__.py
│       │   └── settings.py          ← Pydantic Settings singleton
│       ├── core/
│       │   ├── __init__.py
│       │   ├── models.py            ← ALL domain models (Pydantic)
│       │   ├── registry.py          ← Agent registry (org chart in memory + DB)
│       │   ├── memory.py            ← Memory system (global + injection)
│       │   ├── budget.py            ← Budget tracking + enforcement
│       │   └── communication.py     ← Message protocol (delegate / report)
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── database.py          ← SQLAlchemy async engine + session factory
│       │   ├── orm.py               ← SQLAlchemy ORM models
│       │   └── repositories.py      ← Repository pattern (all DB access here)
│       ├── skills/
│       │   ├── __init__.py
│       │   ├── base.py              ← Skill base class
│       │   ├── catalog.py           ← Built-in skill definitions
│       │   └── registry.py          ← Runtime skill registry per agent
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── base.py              ← Tool base class + global registry
│       │   ├── web_search.py        ← Web search (via Tavily or Brave API)
│       │   ├── code_exec.py         ← Sandboxed Python execution
│       │   └── file_ops.py          ← File read/write/list
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── base.py              ← BaseAgent: lifecycle, LLM call, tool dispatch
│       │   ├── root.py              ← RootAgent (CEO): user interface + org init
│       │   ├── manager.py           ← ManagerAgent: spawn/supervise teams
│       │   └── worker.py            ← WorkerAgent: leaf execution with tools
│       ├── orchestration/
│       │   ├── __init__.py
│       │   ├── graph.py             ← LangGraph team subgraph builder
│       │   ├── spawner.py           ← Agent spawn protocol (parent → child)
│       │   └── executor.py          ← Parallel execution + result aggregation
│       └── api/
│           ├── __init__.py
│           └── cli.py               ← Rich CLI (user ↔ root agent)
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
RootAgent (CEO)
    │   Analyzes pitch → decides org structure (LLM call with spawn_team tool)
    │
    ├──[parallel]──► ManagerAgent (CMO)
    │                    │
    │                    ├──[parallel]──► WorkerAgent (Instagram)
    │                    └──[parallel]──► WorkerAgent (Content)
    │
    └──[parallel]──► ManagerAgent (CTO)
                         │
                         └──[parallel]──► WorkerAgent (Backend)
                                        ► WorkerAgent (Frontend)

Results bubble up:
    worker.report() → manager aggregates → CEO synthesizes → User
```

---

## Domain Models (src/dri/core/models.py)

Key types (all Pydantic v2):

- `AgentRole`: Enum — ROOT, MANAGER, WORKER
- `AgentStatus`: Enum — INITIALIZING, ACTIVE, WAITING, DONE, FAILED
- `AgentConfig`: id, role, mission, parent_id, skills, budget_tokens, model
- `AgentState`: mutable runtime state for an agent
- `Message`: typed envelope for all inter-agent communication
- `DelegateMessage`: parent → child (task + context)
- `ReportMessage`: child → parent (result + status + issues)
- `SpawnRequest`: what a parent sends to spawner to create a child
- `Skill`: name, description, instructions (injected into agent system prompt)
- `Task`: id, description, assigned_to, status, result
- `BudgetAllocation`: total, used, remaining per agent
- `OrgNode`: node in the org chart tree (for registry)

---

## Memory Architecture

Three layers, strictly separated:

1. **Global Store (SQLite)**: org chart, all agents, all tasks, all results. Source of truth.
2. **Context Injection (runtime)**: when parent spawns child, it builds a `ContextPacket`
   containing only what the child needs: its role, mission, skills, budget, and any
   relevant prior results. Child has NO other global access.
3. **Working Memory (prompt)**: the current conversation/task in the agent's active LLM call.
   This is ephemeral and lives only for the duration of one task execution.

---

## Budget System

- Configured in `.env`: `BUDGET_MAX_TOKENS_PER_SESSION` (default: 2_000_000)
- Root agent gets the full budget at session start
- When spawning a child, parent allocates a share (configurable, defaults to proportional split)
- Each LLM call deducts from the agent's budget
- If budget < threshold: agent reports to parent before calling LLM
- Parent can reallocate, continue, or terminate branch
- All budget state persisted to DB for auditability

---

## Communication Protocol

Strictly hierarchical — no lateral communication:

- **Delegate** (parent → child): `DelegateMessage(task, context, budget)`
- **Report** (child → parent): `ReportMessage(task_id, result, status, tokens_used, issues)`
- **Spawn** (manager internal): manager calls `Spawner.spawn(SpawnRequest)` to create children
- **Escalate** (child → parent, unplanned): used when child hits blockers or needs more budget

All messages are typed, validated, logged to DB.

---

## Agent Lifecycle

```
INITIALIZING → ACTIVE → [WAITING for children] → DONE
                    └──────────────────────────► FAILED
```

- `INITIALIZING`: agent config received, system prompt built by parent's context
- `ACTIVE`: executing its task (making LLM calls, using tools)
- `WAITING`: has spawned children, aggregating their results
- `DONE`: result reported to parent, agent archived
- `FAILED`: error reported to parent, parent decides action

---

## LangGraph Pattern

Each "team" (manager + its workers) is a compiled `StateGraph`:

```python
team_graph = StateGraph(TeamState)
team_graph.add_node("supervisor", supervisor_node)   # manager logic
team_graph.add_node("worker", worker_node)            # worker logic
# supervisor uses Send API for parallel workers:
# return [Send("worker", {...}) for task in tasks]
team_graph.add_conditional_edges("supervisor", route, {END: END, "worker": "worker"})
team_graph.add_edge("worker", "supervisor")           # results back to supervisor
```

Unlimited depth: manager nodes can invoke new team_graph runs via tool calls (recursive).

---

## Skills System

Skills are structured instructions injected into an agent's system prompt by its parent.
They are NOT code — they are natural language capability descriptors with structured metadata.

```python
class Skill(BaseModel):
    name: str
    description: str          # what this skill enables
    instructions: str         # how to use this skill (injected verbatim into system prompt)
    required_tools: list[str] # tools needed for this skill
```

Parent builds child's skill set based on the child's role and current company needs.
Skills can be added or revoked by the parent at any time (new context injection).

---

## Tools System

Tools are actual executable capabilities (not just prompt instructions):

| Tool | Description |
|---|---|
| `web_search` | Search the web (Tavily API or Brave API) |
| `code_exec` | Execute Python in a sandboxed subprocess |
| `file_read` | Read file from workspace |
| `file_write` | Write file to workspace |
| `file_list` | List files in workspace |

Tools are registered globally and assigned to agents by their parent (via SpawnRequest).
Each tool is a Pydantic model with an async `execute()` method.
All tool calls are logged to DB with input, output, duration, and token cost.

---

## Configuration (.env)

```
# LLM
ANTHROPIC_API_KEY=your_key_here
DEFAULT_MODEL=claude-sonnet-4-6
ROOT_MODEL=claude-sonnet-4-6

# Budget
BUDGET_MAX_TOKENS_PER_SESSION=2000000
BUDGET_WARNING_THRESHOLD=0.2     # warn parent at 20% remaining
BUDGET_CHILD_DEFAULT_SHARE=0.4   # each child gets 40% of parent's budget

# Tools
TAVILY_API_KEY=optional_for_web_search
BRAVE_API_KEY=optional_for_web_search

# Storage
DATABASE_URL=sqlite+aiosqlite:///./dri_company.db

# Workspace
WORKSPACE_DIR=./workspace        # where agents write files

# Orchestration
MAX_CONCURRENT_AGENTS=20         # global cap on parallel agents
MAX_SPAWN_DEPTH=10               # max hierarchy depth
AGENT_TIMEOUT_SECONDS=300        # per-agent task timeout
```

---

## Current Implementation State

### Completed (all as of 2026-04-22)
- [x] CLAUDE.md
- [x] pyproject.toml
- [x] .env.example
- [x] src/dri/config/settings.py
- [x] src/dri/core/models.py
- [x] src/dri/storage/database.py
- [x] src/dri/storage/orm.py
- [x] src/dri/storage/repositories.py
- [x] src/dri/core/registry.py
- [x] src/dri/core/memory.py
- [x] src/dri/core/budget.py
- [x] src/dri/core/communication.py
- [x] src/dri/skills/base.py
- [x] src/dri/skills/catalog.py
- [x] src/dri/skills/registry.py
- [x] src/dri/tools/base.py + __init__.py
- [x] src/dri/tools/web_search.py
- [x] src/dri/tools/code_exec.py
- [x] src/dri/tools/file_ops.py
- [x] src/dri/agents/base.py
- [x] src/dri/agents/root.py
- [x] src/dri/agents/manager.py
- [x] src/dri/agents/worker.py
- [x] src/dri/orchestration/graph.py
- [x] src/dri/orchestration/spawner.py
- [x] src/dri/orchestration/executor.py
- [x] src/dri/api/cli.py
- [x] tests/unit/ (models, budget, memory, tools, registry)

### Pending
- [ ] tests/integration/ — full end-to-end pitch test (requires ANTHROPIC_API_KEY)
- [ ] Next.js frontend (optional, post-MVP)

---

## Key Invariants (never violate these)

1. **No agent accesses global state directly** — all state goes through the Repository layer.
2. **No lateral communication** — agents only talk to parent or children, never siblings.
3. **All LLM calls go through BaseAgent._call_llm()** — this ensures budget tracking, logging, and prompt caching.
4. **All DB access goes through repositories** — never use ORM models directly in business logic.
5. **All tool calls are async** — never block the event loop.
6. **Parent always outlives children** — a parent cannot be marked DONE until all children are DONE or FAILED.
7. **Budget is always checked before LLM calls** — `BudgetManager.check_and_deduct()` is called in `BaseAgent._call_llm()`.

---

## How to Run

```bash
# Install (uses uv — the project's package manager)
uv sync

# Or install with dev deps for tests:
uv sync --extra dev

# Copy and configure environment
cp .env.example .env
# Edit .env: set ANTHROPIC_API_KEY at minimum

# Run the CLI
uv run dri run

# Or with a pre-set pitch:
uv run dri run --pitch "A SaaS platform for restaurant inventory management"

# Run tests:
uv run pytest

# List past sessions:
uv run dri sessions
```

## Package Manager

**Always use `uv`**, never `pip`. The user has `uv` configured globally.
Frontend (if needed): Next.js. Rich CLI is the MVP interface.

---

## Notes for the Next Agent

- Check `## Current Implementation State` above to know where we left off.
- Always mark files as completed in that checklist when done.
- Never duplicate logic — if something exists in core/, use it everywhere.
- The `settings.py` singleton is imported as `from dri.config.settings import settings` — never read env vars directly elsewhere.
- All async functions use `async def` — no mixing of sync/async without `asyncio.to_thread()`.
- Commit message style: `feat: add X`, `fix: Y`, `refactor: Z`.
