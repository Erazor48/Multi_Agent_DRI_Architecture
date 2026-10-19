"""
FastAPI HTTP server — exposes DRI functionality as REST endpoints.

All long-running operations (create, chat, task) stream via SSE:
  data: {"type": "status", "message": "..."}\n\n
  data: {"type": "result", "text": "..." | "company": {...}}\n\n
  data: {"type": "error", "message": "..."}\n\n

Start with: uv run dri serve
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


@asynccontextmanager
async def _lifespan(app: FastAPI):
    from dri.storage.database import init_db
    await init_db()
    yield


app = FastAPI(title="DRI Multi-Agent API", version="0.1.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request bodies ────────────────────────────────────────────────────────


class CreateCompanyBody(BaseModel):
    pitch: str


class ChatBody(BaseModel):
    message: str


class TaskBody(BaseModel):
    task: str


class DecisionBody(BaseModel):
    note: str = ""


# ── Serialization helpers ─────────────────────────────────────────────────


def _company_dict(c: Any) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "vision": c.vision,
        "pitch": c.pitch,
        "org_structure": c.org_structure,
        "status": c.status,
        "created_at": c.created_at.isoformat(),
    }


def _agent_dict(a: Any) -> dict:
    return {
        "id": a.id,
        "title": a.title,
        "role": a.role,
        "dept_slug": a.dept_slug,
        "task_count": a.task_count,
        "success_count": a.success_count,
        "success_rate": a.success_rate,
        "token_budget": a.token_budget,
        "notes": a.notes,
        "status": a.status,
        "last_active_at": a.last_active_at.isoformat(),
        "created_at": a.created_at.isoformat(),
    }


# ── SSE streaming helper ──────────────────────────────────────────────────


async def _sse_stream(
    factory: Callable[[Callable[[str], None]], Any],
    result_key: str = "text",
) -> AsyncGenerator[str, None]:
    """
    Runs factory(on_status) in a background task, streaming status callbacks
    as SSE events. Sends a final result or error event when done.

    factory must be a coroutine function that accepts on_status as its only arg.
    """
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def _cb(msg: str) -> None:
        queue.put_nowait(json.dumps({"type": "status", "message": msg}))

    async def _run() -> None:
        try:
            result = await factory(_cb)
            if isinstance(result, dict):
                await queue.put(json.dumps({"type": "result", result_key: result}))
            else:
                await queue.put(json.dumps({"type": "result", result_key: result}))
        except Exception as exc:
            await queue.put(json.dumps({"type": "error", "message": str(exc)}))
        finally:
            await queue.put(None)

    asyncio.create_task(_run())

    while True:
        item = await queue.get()
        if item is None:
            return
        yield f"data: {item}\n\n"


# ── Auth dependency ───────────────────────────────────────────────────────


def _resolve_user_id(x_user_id: str | None = Header(default=None)) -> str:
    """Return X-User-ID header when present (dashboard), else local CLI user."""
    if x_user_id:
        return x_user_id
    from dri.config.state import get_local_user_id
    return get_local_user_id()


# ── Company resolution ────────────────────────────────────────────────────


async def _get_company_or_404(company_id: str) -> Any:
    from dri.storage.database import get_session
    from dri.storage.repositories import PersistentCompanyRepository

    async with get_session() as db:
        repo = PersistentCompanyRepository(db)
        company = await repo.get(company_id)
        if company is None:
            company = await repo.get_by_prefix(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail=f"Company '{company_id}' not found")
    return company


def _get_workspace(company_name: str) -> Path:
    import unicodedata
    import re
    from dri.config.settings import get_settings

    name = company_name
    normalized = unicodedata.normalize("NFD", name.lower())
    ascii_only = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    return Path(get_settings().workspace_dir) / slug


# ── Root ─────────────────────────────────────────────────────────────────


@app.get("/")
async def root() -> dict:
    return {"name": "DRI Multi-Agent API", "version": "0.1.0", "docs": "/docs"}


# ── Companies ─────────────────────────────────────────────────────────────


@app.get("/api/companies")
async def list_companies(user_id: str = Depends(_resolve_user_id)) -> list[dict]:
    from dri.storage.database import get_session
    from dri.storage.repositories import PersistentCompanyRepository

    async with get_session() as db:
        repo = PersistentCompanyRepository(db)
        companies = await repo.list_active(user_id=user_id)
    return [_company_dict(c) for c in companies]


@app.post("/api/companies", status_code=201)
async def create_company(
    body: CreateCompanyBody,
    user_id: str = Depends(_resolve_user_id),
) -> StreamingResponse:
    """SSE stream. Final event: {type: result, company: {...}}"""
    if not body.pitch.strip():
        raise HTTPException(status_code=422, detail="pitch cannot be empty")

    async def _factory(on_status: Callable[[str], None]) -> dict:
        from dri.orchestration.company_executor import CompanyExecutor
        company = await CompanyExecutor.create(body.pitch, on_status=on_status, user_id=user_id)
        return _company_dict(company)

    return StreamingResponse(_sse_stream(_factory, result_key="company"), media_type="text/event-stream")


@app.get("/api/companies/{company_id}")
async def get_company(company_id: str) -> dict:
    company = await _get_company_or_404(company_id)
    return _company_dict(company)


@app.delete("/api/companies/{company_id}", status_code=204)
async def delete_company(company_id: str) -> None:
    company = await _get_company_or_404(company_id)
    from dri.storage.database import get_session
    from dri.storage.repositories import PersistentCompanyRepository

    async with get_session() as db:
        repo = PersistentCompanyRepository(db)
        await repo.delete(company.id)


# ── Company actions (SSE) ─────────────────────────────────────────────────


@app.post("/api/companies/{company_id}/chat")
async def chat(company_id: str, body: ChatBody) -> StreamingResponse:
    """SSE stream. Final event: {type: result, text: "..."}"""
    company = await _get_company_or_404(company_id)

    async def _factory(on_status: Callable[[str], None]) -> str:
        from dri.orchestration.company_executor import CompanyExecutor
        return await CompanyExecutor.chat(company.id, body.message, on_status=on_status)

    return StreamingResponse(_sse_stream(_factory), media_type="text/event-stream")


@app.post("/api/companies/{company_id}/task")
async def run_task(company_id: str, body: TaskBody) -> StreamingResponse:
    """SSE stream. Final event: {type: result, text: "..."}"""
    company = await _get_company_or_404(company_id)

    async def _factory(on_status: Callable[[str], None]) -> str:
        from dri.orchestration.company_executor import CompanyExecutor
        return await CompanyExecutor.task(company.id, body.task, on_status=on_status)

    return StreamingResponse(_sse_stream(_factory), media_type="text/event-stream")


# ── Approvals ─────────────────────────────────────────────────────────────


def _load_approvals(workspace: Path) -> list[dict]:
    pending_file = workspace / "shared" / "_pending_approvals.json"
    if not pending_file.exists():
        return []
    try:
        return json.loads(pending_file.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_approvals(workspace: Path, actions: list[dict]) -> None:
    pending_file = workspace / "shared" / "_pending_approvals.json"
    pending_file.write_text(json.dumps(actions, indent=2, ensure_ascii=False), encoding="utf-8")


@app.get("/api/companies/{company_id}/approvals")
async def list_approvals(
    company_id: str,
    all: bool = False,
) -> list[dict]:
    company = await _get_company_or_404(company_id)
    workspace = _get_workspace(company.name)
    actions = _load_approvals(workspace)
    if not all:
        actions = [a for a in actions if a.get("status") == "pending"]
    return actions


@app.post("/api/companies/{company_id}/approvals/{action_id}/approve")
async def approve_action(company_id: str, action_id: int, body: DecisionBody) -> dict:
    """Approve action by 1-based index (as shown in list)."""
    company = await _get_company_or_404(company_id)
    workspace = _get_workspace(company.name)
    actions = _load_approvals(workspace)

    if action_id < 1 or action_id > len(actions):
        raise HTTPException(status_code=404, detail=f"Action #{action_id} not found")

    from datetime import timezone
    a = actions[action_id - 1]
    a["status"] = "approved"
    a["decided_at"] = datetime.now(timezone.utc).isoformat()
    a["decision_note"] = body.note or None
    _save_approvals(workspace, actions)
    return a


@app.post("/api/companies/{company_id}/approvals/{action_id}/reject")
async def reject_action(company_id: str, action_id: int, body: DecisionBody) -> dict:
    """Reject action by 1-based index."""
    company = await _get_company_or_404(company_id)
    workspace = _get_workspace(company.name)
    actions = _load_approvals(workspace)

    if action_id < 1 or action_id > len(actions):
        raise HTTPException(status_code=404, detail=f"Action #{action_id} not found")

    from datetime import timezone
    a = actions[action_id - 1]
    a["status"] = "rejected"
    a["decided_at"] = datetime.now(timezone.utc).isoformat()
    a["decision_note"] = body.note or None
    _save_approvals(workspace, actions)
    return a


# ── Team ──────────────────────────────────────────────────────────────────


@app.get("/api/companies/{company_id}/team")
async def list_team(company_id: str) -> list[dict]:
    company = await _get_company_or_404(company_id)
    from dri.storage.database import get_session
    from dri.storage.repositories import CompanyAgentRepository

    async with get_session() as db:
        repo = CompanyAgentRepository(db)
        agents = await repo.list_active(company.id)
    return [_agent_dict(a) for a in agents]


# ── Status snapshot ───────────────────────────────────────────────────────


@app.get("/api/companies/{company_id}/status")
async def company_status(company_id: str) -> dict:
    company = await _get_company_or_404(company_id)
    workspace = _get_workspace(company.name)

    from dri.storage.database import get_session
    from dri.storage.repositories import CompanyAgentRepository

    async with get_session() as db:
        repo = CompanyAgentRepository(db)
        agents = await repo.list_active(company.id)

    pending_count = 0
    pending_path = workspace / "shared" / "_pending_approvals.json"
    if pending_path.exists():
        try:
            pending_count = sum(
                1 for a in json.loads(pending_path.read_text(encoding="utf-8"))
                if a.get("status") == "pending"
            )
        except Exception:
            pass

    recent_tasks: list[str] = []
    history_path = workspace / "shared" / "_company_history.md"
    if history_path.exists():
        raw = history_path.read_text(encoding="utf-8")
        entries = [e.strip() for e in raw.split("\n## ") if e.strip()]
        recent_tasks = [e.splitlines()[0].lstrip("# ").strip() for e in entries[-5:]]

    _SKIP = {"node_modules", ".next", "__pycache__", ".git"}
    file_count = 0
    if workspace.exists():
        for p in workspace.rglob("*"):
            if any(s in p.parts for s in _SKIP):
                continue
            if p.is_file():
                file_count += 1

    return {
        **_company_dict(company),
        "team": [_agent_dict(a) for a in agents],
        "pending_approvals": pending_count,
        "file_count": file_count,
        "recent_tasks": recent_tasks,
    }


# ── Errors ────────────────────────────────────────────────────────────────


@app.get("/api/companies/{company_id}/errors")
async def company_errors(company_id: str, limit: int = 20) -> list[dict]:
    company = await _get_company_or_404(company_id)
    workspace = _get_workspace(company.name)
    errors_file = workspace / "shared" / "_errors.jsonl"

    if not errors_file.exists():
        return []

    entries = []
    try:
        for line in errors_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    except Exception:
        return []

    return entries[-limit:]
