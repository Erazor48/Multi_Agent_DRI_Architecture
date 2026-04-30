"""Unit tests for CompanyAgentRepository (Layer 5 — persistent agent identities)."""
from __future__ import annotations

import pytest
import pytest_asyncio

from dri.core.models import CompanyAgent
from dri.storage.repositories import CompanyAgentRepository


COMPANY_ID = "test-company-001"
COMPANY_ID_2 = "test-company-002"


class TestCompanyAgentGetOrCreate:
    @pytest.mark.asyncio
    async def test_creates_new_agent(self, db_session):
        repo = CompanyAgentRepository(db_session)
        agent = await repo.get_or_create(COMPANY_ID, "SEO Specialist", "worker", "seo-specialist")
        assert isinstance(agent, CompanyAgent)
        assert agent.title == "SEO Specialist"
        assert agent.role == "worker"
        assert agent.dept_slug == "seo-specialist"
        assert agent.company_id == COMPANY_ID
        assert agent.task_count == 0
        assert agent.success_count == 0
        assert agent.status == "active"

    @pytest.mark.asyncio
    async def test_returns_existing_agent(self, db_session):
        repo = CompanyAgentRepository(db_session)
        a1 = await repo.get_or_create(COMPANY_ID, "Content Writer", "worker", "content-writer")
        a2 = await repo.get_or_create(COMPANY_ID, "Content Writer", "worker", "content-writer")
        assert a1.id == a2.id

    @pytest.mark.asyncio
    async def test_same_title_different_companies(self, db_session):
        repo = CompanyAgentRepository(db_session)
        a1 = await repo.get_or_create(COMPANY_ID, "CMO", "manager", "cmo")
        a2 = await repo.get_or_create(COMPANY_ID_2, "CMO", "manager", "cmo")
        assert a1.id != a2.id
        assert a1.company_id == COMPANY_ID
        assert a2.company_id == COMPANY_ID_2


class TestCompanyAgentRecordTask:
    @pytest.mark.asyncio
    async def test_increments_task_count(self, db_session):
        repo = CompanyAgentRepository(db_session)
        agent = await repo.get_or_create(COMPANY_ID, "Analyst", "worker", "analyst")
        await repo.record_task(agent.id, success=True)
        updated = await repo.get_by_title(COMPANY_ID, "Analyst")
        assert updated.task_count == 1
        assert updated.success_count == 1

    @pytest.mark.asyncio
    async def test_failed_task_increments_count_not_success(self, db_session):
        repo = CompanyAgentRepository(db_session)
        agent = await repo.get_or_create(COMPANY_ID, "Developer", "worker", "developer")
        await repo.record_task(agent.id, success=False)
        updated = await repo.get_by_title(COMPANY_ID, "Developer")
        assert updated.task_count == 1
        assert updated.success_count == 0

    @pytest.mark.asyncio
    async def test_multiple_tasks_accumulate(self, db_session):
        repo = CompanyAgentRepository(db_session)
        agent = await repo.get_or_create(COMPANY_ID, "Designer", "worker", "designer")
        await repo.record_task(agent.id, success=True)
        await repo.record_task(agent.id, success=True)
        await repo.record_task(agent.id, success=False)
        updated = await repo.get_by_title(COMPANY_ID, "Designer")
        assert updated.task_count == 3
        assert updated.success_count == 2

    @pytest.mark.asyncio
    async def test_success_rate_property(self, db_session):
        repo = CompanyAgentRepository(db_session)
        agent = await repo.get_or_create(COMPANY_ID, "Copywriter", "worker", "copywriter")
        await repo.record_task(agent.id, success=True)
        await repo.record_task(agent.id, success=False)
        updated = await repo.get_by_title(COMPANY_ID, "Copywriter")
        assert updated.success_rate == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_success_rate_zero_tasks(self, db_session):
        repo = CompanyAgentRepository(db_session)
        agent = await repo.get_or_create(COMPANY_ID, "Strategist", "manager", "strategist")
        assert agent.success_rate == 0.0


class TestCompanyAgentListActive:
    @pytest.mark.asyncio
    async def test_returns_only_active(self, db_session):
        repo = CompanyAgentRepository(db_session)
        active = await repo.get_or_create(COMPANY_ID, "Active Agent", "worker", "active-agent")
        inactive = await repo.get_or_create(COMPANY_ID, "Inactive Agent", "worker", "inactive-agent")
        await repo.set_status(inactive.id, "inactive")
        agents = await repo.list_active(COMPANY_ID)
        titles = [a.title for a in agents]
        assert "Active Agent" in titles
        assert "Inactive Agent" not in titles

    @pytest.mark.asyncio
    async def test_scoped_to_company(self, db_session):
        repo = CompanyAgentRepository(db_session)
        await repo.get_or_create(COMPANY_ID, "Agent A", "worker", "agent-a")
        await repo.get_or_create(COMPANY_ID_2, "Agent B", "worker", "agent-b")
        agents_1 = await repo.list_active(COMPANY_ID)
        agents_2 = await repo.list_active(COMPANY_ID_2)
        titles_1 = [a.title for a in agents_1]
        titles_2 = [a.title for a in agents_2]
        assert "Agent A" in titles_1
        assert "Agent B" not in titles_1
        assert "Agent B" in titles_2
        assert "Agent A" not in titles_2


class TestCompanyAgentMutators:
    @pytest.mark.asyncio
    async def test_set_notes(self, db_session):
        repo = CompanyAgentRepository(db_session)
        agent = await repo.get_or_create(COMPANY_ID, "Note Agent", "worker", "note-agent")
        await repo.set_notes(agent.id, "Needs improvement on X")
        updated = await repo.get_by_title(COMPANY_ID, "Note Agent")
        assert updated.notes == "Needs improvement on X"

    @pytest.mark.asyncio
    async def test_set_status_inactive(self, db_session):
        repo = CompanyAgentRepository(db_session)
        agent = await repo.get_or_create(COMPANY_ID, "Status Agent", "worker", "status-agent")
        assert agent.status == "active"
        await repo.set_status(agent.id, "inactive")
        updated = await repo.get_by_title(COMPANY_ID, "Status Agent")
        assert updated.status == "inactive"

    @pytest.mark.asyncio
    async def test_set_budget(self, db_session):
        repo = CompanyAgentRepository(db_session)
        agent = await repo.get_or_create(COMPANY_ID, "Budget Agent", "manager", "budget-agent")
        assert agent.token_budget == 0
        await repo.set_budget(agent.id, 500_000)
        updated = await repo.get_by_title(COMPANY_ID, "Budget Agent")
        assert updated.token_budget == 500_000

    @pytest.mark.asyncio
    async def test_get_by_title_not_found(self, db_session):
        repo = CompanyAgentRepository(db_session)
        result = await repo.get_by_title(COMPANY_ID, "Ghost Agent")
        assert result is None
