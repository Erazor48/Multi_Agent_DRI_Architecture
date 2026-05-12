"""Unit tests for the FastAPI HTTP server."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def api_client():
    """AsyncClient backed by in-memory DB, with app lifespan triggered."""
    import httpx
    from httpx import ASGITransport

    from dri.api.server import app as fastapi_app
    from dri.config.settings import get_settings
    from dri.storage.database import drop_db, reset_engine

    get_settings.cache_clear()
    reset_engine(test_db_url="sqlite+aiosqlite:///:memory:")
    from dri.storage.database import init_db
    await init_db()

    async with httpx.AsyncClient(
        transport=ASGITransport(app=fastapi_app),
        base_url="http://test",
    ) as client:
        yield client

    await drop_db()
    reset_engine()
    get_settings.cache_clear()


def _make_company(
    company_id: str = "abc-123",
    name: str = "Acme Corp",
    vision: str = "Change the world",
    pitch: str = "We make things",
) -> "PersistentCompany":  # type: ignore[name-defined]
    from datetime import datetime, timezone

    from dri.core.models import PersistentCompany

    return PersistentCompany(
        id=company_id,
        name=name,
        vision=vision,
        pitch=pitch,
        org_structure=[{"title": "CEO", "dept": "executive"}],
        status="active",
        user_id="user-1",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


# ── GET /api/companies ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_companies_empty(api_client):
    with patch("dri.config.state.get_local_user_id", return_value="user-1"):
        r = await api_client.get("/api/companies")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_companies_returns_user_companies(api_client):
    company = _make_company()
    mock_repo = AsyncMock()
    mock_repo.list_active = AsyncMock(return_value=[company])

    with (
        patch("dri.config.state.get_local_user_id", return_value="user-1"),
        patch("dri.storage.repositories.PersistentCompanyRepository", return_value=mock_repo),
    ):
        r = await api_client.get("/api/companies")

    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["id"] == "abc-123"
    assert data[0]["name"] == "Acme Corp"
    assert "org_structure" in data[0]


# ── GET /api/companies/{id} ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_company_not_found(api_client):
    mock_repo = AsyncMock()
    mock_repo.get = AsyncMock(return_value=None)
    mock_repo.get_by_prefix = AsyncMock(return_value=None)

    with patch("dri.storage.repositories.PersistentCompanyRepository", return_value=mock_repo):
        r = await api_client.get("/api/companies/unknown-id")

    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_company_found(api_client):
    company = _make_company()
    mock_repo = AsyncMock()
    mock_repo.get = AsyncMock(return_value=company)

    with patch("dri.storage.repositories.PersistentCompanyRepository", return_value=mock_repo):
        r = await api_client.get("/api/companies/abc-123")

    assert r.status_code == 200
    data = r.json()
    assert data["id"] == "abc-123"
    assert data["name"] == "Acme Corp"
    assert data["vision"] == "Change the world"


@pytest.mark.asyncio
async def test_get_company_by_prefix(api_client):
    company = _make_company()
    mock_repo = AsyncMock()
    mock_repo.get = AsyncMock(return_value=None)
    mock_repo.get_by_prefix = AsyncMock(return_value=company)

    with patch("dri.storage.repositories.PersistentCompanyRepository", return_value=mock_repo):
        r = await api_client.get("/api/companies/abc")

    assert r.status_code == 200
    assert r.json()["id"] == "abc-123"


# ── DELETE /api/companies/{id} ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_company_not_found(api_client):
    mock_repo = AsyncMock()
    mock_repo.get = AsyncMock(return_value=None)
    mock_repo.get_by_prefix = AsyncMock(return_value=None)

    with patch("dri.storage.repositories.PersistentCompanyRepository", return_value=mock_repo):
        r = await api_client.delete("/api/companies/unknown-id")

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_company_success(api_client):
    company = _make_company()
    mock_repo = AsyncMock()
    mock_repo.get = AsyncMock(return_value=company)
    mock_repo.delete = AsyncMock(return_value=True)

    with patch("dri.storage.repositories.PersistentCompanyRepository", return_value=mock_repo):
        r = await api_client.delete("/api/companies/abc-123")

    assert r.status_code == 204
    mock_repo.delete.assert_awaited_once_with("abc-123")


# ── GET /api/companies/{id}/team ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_team_empty(api_client):
    company = _make_company()
    mock_company_repo = AsyncMock()
    mock_company_repo.get = AsyncMock(return_value=company)
    mock_agent_repo = AsyncMock()
    mock_agent_repo.list_active = AsyncMock(return_value=[])

    with (
        patch("dri.storage.repositories.PersistentCompanyRepository", return_value=mock_company_repo),
        patch("dri.storage.repositories.CompanyAgentRepository", return_value=mock_agent_repo),
    ):
        r = await api_client.get("/api/companies/abc-123/team")

    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_team_returns_agents(api_client):
    from datetime import datetime, timezone

    from dri.core.models import CompanyAgent

    company = _make_company()
    agent = CompanyAgent(
        id="agent-1",
        company_id="abc-123",
        title="Marketing Manager",
        role="manager",
        dept_slug="marketing",
        task_count=5,
        success_count=4,
        status="active",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_active_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    mock_company_repo = AsyncMock()
    mock_company_repo.get = AsyncMock(return_value=company)
    mock_agent_repo = AsyncMock()
    mock_agent_repo.list_active = AsyncMock(return_value=[agent])

    with (
        patch("dri.storage.repositories.PersistentCompanyRepository", return_value=mock_company_repo),
        patch("dri.storage.repositories.CompanyAgentRepository", return_value=mock_agent_repo),
    ):
        r = await api_client.get("/api/companies/abc-123/team")

    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["title"] == "Marketing Manager"
    assert data[0]["success_rate"] == pytest.approx(0.8)


# ── GET /api/companies/{id}/approvals ─────────────────────────────────────


@pytest.mark.asyncio
async def test_list_approvals_no_workspace(api_client, tmp_path):
    company = _make_company()
    mock_repo = AsyncMock()
    mock_repo.get = AsyncMock(return_value=company)

    with (
        patch("dri.storage.repositories.PersistentCompanyRepository", return_value=mock_repo),
        patch("dri.api.server._get_workspace", return_value=tmp_path / "no-such-dir"),
    ):
        r = await api_client.get("/api/companies/abc-123/approvals")

    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_approvals_pending_only(api_client, tmp_path):
    company = _make_company()

    workspace = tmp_path / "acme-corp"
    shared = workspace / "shared"
    shared.mkdir(parents=True)
    actions = [
        {"status": "pending", "action_type": "email", "proposed_by": "CEO", "recipient": "a@b.com"},
        {"status": "approved", "action_type": "webhook", "proposed_by": "COO"},
    ]
    (shared / "_pending_approvals.json").write_text(json.dumps(actions))

    mock_repo = AsyncMock()
    mock_repo.get = AsyncMock(return_value=company)

    with (
        patch("dri.storage.repositories.PersistentCompanyRepository", return_value=mock_repo),
        patch("dri.api.server._get_workspace", return_value=workspace),
    ):
        r = await api_client.get("/api/companies/abc-123/approvals")

    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_list_approvals_all(api_client, tmp_path):
    company = _make_company()

    workspace = tmp_path / "acme-corp"
    (workspace / "shared").mkdir(parents=True)
    actions = [
        {"status": "pending", "action_type": "email"},
        {"status": "approved", "action_type": "webhook"},
    ]
    (workspace / "shared" / "_pending_approvals.json").write_text(json.dumps(actions))

    mock_repo = AsyncMock()
    mock_repo.get = AsyncMock(return_value=company)

    with (
        patch("dri.storage.repositories.PersistentCompanyRepository", return_value=mock_repo),
        patch("dri.api.server._get_workspace", return_value=workspace),
    ):
        r = await api_client.get("/api/companies/abc-123/approvals?all=true")

    assert r.status_code == 200
    assert len(r.json()) == 2


# ── POST /api/companies/{id}/approvals/{n}/approve ────────────────────────


@pytest.mark.asyncio
async def test_approve_action(api_client, tmp_path):
    company = _make_company()

    workspace = tmp_path / "acme-corp"
    (workspace / "shared").mkdir(parents=True)
    actions = [{"status": "pending", "action_type": "email", "proposed_by": "CEO"}]
    (workspace / "shared" / "_pending_approvals.json").write_text(json.dumps(actions))

    mock_repo = AsyncMock()
    mock_repo.get = AsyncMock(return_value=company)

    with (
        patch("dri.storage.repositories.PersistentCompanyRepository", return_value=mock_repo),
        patch("dri.api.server._get_workspace", return_value=workspace),
    ):
        r = await api_client.post(
            "/api/companies/abc-123/approvals/1/approve",
            json={"note": "Looks good"},
        )

    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "approved"
    assert data["decision_note"] == "Looks good"

    # Verify file was updated
    saved = json.loads((workspace / "shared" / "_pending_approvals.json").read_text())
    assert saved[0]["status"] == "approved"


@pytest.mark.asyncio
async def test_approve_action_out_of_range(api_client, tmp_path):
    company = _make_company()
    workspace = tmp_path / "acme-corp"
    (workspace / "shared").mkdir(parents=True)
    (workspace / "shared" / "_pending_approvals.json").write_text("[]")

    mock_repo = AsyncMock()
    mock_repo.get = AsyncMock(return_value=company)

    with (
        patch("dri.storage.repositories.PersistentCompanyRepository", return_value=mock_repo),
        patch("dri.api.server._get_workspace", return_value=workspace),
    ):
        r = await api_client.post(
            "/api/companies/abc-123/approvals/99/approve",
            json={},
        )

    assert r.status_code == 404


# ── POST /api/companies (validation) ─────────────────────────────────────


@pytest.mark.asyncio
async def test_create_company_empty_pitch(api_client):
    r = await api_client.post("/api/companies", json={"pitch": "  "})
    assert r.status_code == 422


# ── POST /api/companies/{id}/chat (SSE) ───────────────────────────────────


@pytest.mark.asyncio
async def test_chat_streams_sse(api_client):
    company = _make_company()
    mock_repo = AsyncMock()
    mock_repo.get = AsyncMock(return_value=company)

    async def mock_chat(company_id, message, on_status=None):
        if on_status:
            on_status("CEO thinking...")
        return "Hello, I am your CEO."

    with (
        patch("dri.storage.repositories.PersistentCompanyRepository", return_value=mock_repo),
        patch("dri.orchestration.company_executor.CompanyExecutor.chat", new=mock_chat),
    ):
        r = await api_client.post(
            "/api/companies/abc-123/chat",
            json={"message": "How are we doing?"},
        )

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    events = [
        json.loads(line[len("data: "):])
        for line in r.text.splitlines()
        if line.startswith("data: ")
    ]
    types = [e["type"] for e in events]
    assert "status" in types
    assert "result" in types
    result_event = next(e for e in events if e["type"] == "result")
    assert result_event["text"] == "Hello, I am your CEO."


# ── POST /api/companies/{id}/task (SSE) ───────────────────────────────────


@pytest.mark.asyncio
async def test_task_streams_sse(api_client):
    company = _make_company()
    mock_repo = AsyncMock()
    mock_repo.get = AsyncMock(return_value=company)

    async def mock_task(company_id, task, on_status=None):
        if on_status:
            on_status("Spawning team...")
        return "Task complete: market analysis done."

    with (
        patch("dri.storage.repositories.PersistentCompanyRepository", return_value=mock_repo),
        patch("dri.orchestration.company_executor.CompanyExecutor.task", new=mock_task),
    ):
        r = await api_client.post(
            "/api/companies/abc-123/task",
            json={"task": "Analyze the market"},
        )

    assert r.status_code == 200
    events = [
        json.loads(line[len("data: "):])
        for line in r.text.splitlines()
        if line.startswith("data: ")
    ]
    result_event = next((e for e in events if e["type"] == "result"), None)
    assert result_event is not None
    assert "market analysis done" in result_event["text"]


# ── GET /api/companies/{id}/errors ────────────────────────────────────────


@pytest.mark.asyncio
async def test_errors_no_file(api_client, tmp_path):
    company = _make_company()
    mock_repo = AsyncMock()
    mock_repo.get = AsyncMock(return_value=company)

    with (
        patch("dri.storage.repositories.PersistentCompanyRepository", return_value=mock_repo),
        patch("dri.api.server._get_workspace", return_value=tmp_path / "no-workspace"),
    ):
        r = await api_client.get("/api/companies/abc-123/errors")

    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_errors_returns_entries(api_client, tmp_path):
    company = _make_company()
    workspace = tmp_path / "acme-corp"
    (workspace / "shared").mkdir(parents=True)
    entries = [
        {"ts": "2026-01-01T10:00:00", "outcome": "failed", "task": "Write blog post"},
        {"ts": "2026-01-02T11:00:00", "outcome": "partial", "task": "Market analysis"},
    ]
    (workspace / "shared" / "_errors.jsonl").write_text(
        "\n".join(json.dumps(e) for e in entries)
    )

    mock_repo = AsyncMock()
    mock_repo.get = AsyncMock(return_value=company)

    with (
        patch("dri.storage.repositories.PersistentCompanyRepository", return_value=mock_repo),
        patch("dri.api.server._get_workspace", return_value=workspace),
    ):
        r = await api_client.get("/api/companies/abc-123/errors")

    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["outcome"] == "failed"
