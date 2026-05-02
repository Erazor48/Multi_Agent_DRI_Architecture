"""Unit tests for PersistentCompanyRepository, including delete()."""
from __future__ import annotations

import pytest
import pytest_asyncio

from dri.core.models import PersistentCompany
from dri.storage.repositories import (
    CompanyAgentRepository,
    CompanyMessageRepository,
    PersistentCompanyRepository,
)


async def _make_company(db_session, name: str = "Test Co", pitch: str = "A test pitch") -> PersistentCompany:
    repo = PersistentCompanyRepository(db_session)
    company = PersistentCompany(
        name=name,
        vision="Test vision",
        pitch=pitch,
        org_structure=[{"title": "CTO", "slug": "cto"}],
    )
    await repo.create(company)
    return company


class TestPersistentCompanyRepositoryDelete:
    @pytest.mark.asyncio
    async def test_delete_returns_true_when_found(self, db_session):
        company = await _make_company(db_session)
        repo = PersistentCompanyRepository(db_session)
        result = await repo.delete(company.id)
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_returns_false_when_not_found(self, db_session):
        repo = PersistentCompanyRepository(db_session)
        result = await repo.delete("nonexistent-id-xyz")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_removes_company_from_db(self, db_session):
        company = await _make_company(db_session)
        repo = PersistentCompanyRepository(db_session)
        await repo.delete(company.id)
        retrieved = await repo.get(company.id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_removes_company_from_list_active(self, db_session):
        company = await _make_company(db_session)
        repo = PersistentCompanyRepository(db_session)
        before = await repo.list_active()
        assert any(c.id == company.id for c in before)
        await repo.delete(company.id)
        after = await repo.list_active()
        assert not any(c.id == company.id for c in after)

    @pytest.mark.asyncio
    async def test_delete_cascades_messages(self, db_session):
        from dri.core.models import CompanyMessage
        company = await _make_company(db_session)
        msg_repo = CompanyMessageRepository(db_session)
        await msg_repo.add(CompanyMessage(company_id=company.id, role="user", content="hello"))
        await msg_repo.add(CompanyMessage(company_id=company.id, role="ceo", content="hi there"))

        co_repo = PersistentCompanyRepository(db_session)
        await co_repo.delete(company.id)

        remaining = await msg_repo.list_by_company(company.id)
        assert remaining == []

    @pytest.mark.asyncio
    async def test_delete_cascades_agents(self, db_session):
        company = await _make_company(db_session)
        agent_repo = CompanyAgentRepository(db_session)
        await agent_repo.get_or_create(company.id, "Dev", "worker", "dev")

        co_repo = PersistentCompanyRepository(db_session)
        await co_repo.delete(company.id)

        remaining = await agent_repo.list_active(company.id)
        assert remaining == []

    @pytest.mark.asyncio
    async def test_delete_does_not_affect_other_companies(self, db_session):
        c1 = await _make_company(db_session, name="Alpha")
        c2 = await _make_company(db_session, name="Beta")
        repo = PersistentCompanyRepository(db_session)
        await repo.delete(c1.id)
        c2_check = await repo.get(c2.id)
        assert c2_check is not None
        assert c2_check.name == "Beta"
