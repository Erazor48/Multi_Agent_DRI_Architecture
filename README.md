# Multi-Agent DRI Architecture

A platform where you pitch a business idea to a root AI agent (the CEO) and a hierarchical multi-agent "company" organizes itself to work on it. You only talk to the CEO; the rest of the hierarchy is handled by the agents.

The design follows the DRI (Directly Responsible Individual) model:

- Every agent has one role and one mission.
- An agent only knows its parent and its direct children.
- A parent creates, configures, monitors and, if needed, removes its children.
- The parent decides which context (skills, constraints, budget) each child receives.

> Status: experimental personal project. `CLAUDE.md` is the detailed, up-to-date description of the architecture and the implementation state.

## Features

- Two modes: a one-shot session (`dri run`) and persistent companies (`dri company ...`) with a database and a per-company workspace.
- Orchestration with Python `asyncio` and a spawner that creates agents on demand, with a token budget split between parents and children.
- Two LLM providers: Google Gemini or Anthropic Claude, selected with `LLM_PROVIDER`.
- Per-agent tools: web search (Tavily/Brave), file operations with role-based access, sandboxed shell with an executable allowlist, code execution, text-to-speech.
- Approval flow for real-world actions: agents propose actions, you review them with `dri company approvals`. Connectors exist for SMTP and SendGrid email, Twilio SMS, Slack, LinkedIn, GitHub, YouTube and webhooks.
- Persistent agent memory and a company knowledge base, stored in the workspace.
- CLI built with Typer and Rich: budget and cost per task, error log, file tree, agent team notes.

## Install

Requirements: Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev
cp .env.example .env     # then set your API key (GOOGLE_API_KEY or ANTHROPIC_API_KEY)
```

`manim` is a declared dependency and builds `pycairo`, which needs the system cairo development headers. If `uv sync` fails on `pycairo`, install those headers for your OS first.

## Usage

```bash
uv run dri run                                   # one-shot session
uv run dri run --pitch "My idea" --budget 500000

uv run dri company create --pitch "My idea"      # persistent company
uv run dri company chat --id <ID>
uv run dri company task --task "Produce a market analysis report"
uv run dri company budget --id <ID>
uv run dri company approvals list
```

`uv run dri --help` lists every command. `CLAUDE.md` has the full command reference.

External actions (emails, posts, pushes) are never executed directly: they wait for your `approvals approve`.

## Tests

```bash
uv run pytest tests/unit
```

Integration tests under `tests/integration` call real LLM providers and connectors and need valid credentials.

## Layout

```
src/dri/
  agents/          root (CEO), manager and worker agents
  orchestration/   spawner and executors
  core/            domain models, registry, budget, memory, messages
  llm/             Gemini and Anthropic providers
  tools/           search, files, shell, code, external actions, TTS
  connectors/      email, SMS, Slack, LinkedIn, GitHub, YouTube, webhook
  storage/         SQLAlchemy async (SQLite by default)
  api/cli.py       Typer CLI
tests/             unit and integration tests
```

## Stack

Python 3.12, asyncio, Pydantic v2, SQLAlchemy 2 (async) with SQLite, Typer, Rich, Anthropic and Google GenAI SDKs.
