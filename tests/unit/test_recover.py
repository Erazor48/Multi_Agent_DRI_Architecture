"""Unit tests for orphan workspace recovery (recover_scan)."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_recover_scan_detects_orphan(tmp_path, monkeypatch, db_session):
    """A workspace folder with shared/ and no DB record is returned as an orphan."""
    from pathlib import Path

    # Create a fake company workspace with shared/ and a minimal KB
    company_folder = tmp_path / "test-company"
    shared_dir = company_folder / "shared"
    shared_dir.mkdir(parents=True)
    kb_file = shared_dir / "_company_knowledge.md"
    kb_file.write_text("# Test Company\n\nSome KB content.", encoding="utf-8")

    # Patch settings.workspace_dir to point to our tmp_path
    import dri.orchestration.company_executor as ce_module
    original_settings = ce_module.settings

    class _FakeSettings:
        workspace_dir = tmp_path

    monkeypatch.setattr(ce_module, "settings", _FakeSettings())

    try:
        from dri.orchestration.company_executor import CompanyExecutor
        orphans = await CompanyExecutor.recover_scan()
    finally:
        monkeypatch.setattr(ce_module, "settings", original_settings)

    assert len(orphans) == 1
    assert orphans[0].folder_name == "test-company"
    assert orphans[0].inferred_name  # non-empty


@pytest.mark.asyncio
async def test_recover_scan_ignores_known_company(tmp_path, monkeypatch, db_session):
    """A workspace folder whose slug matches a DB company is not returned as orphan."""
    from dri.core.models import PersistentCompany
    from dri.storage.repositories import PersistentCompanyRepository

    # Register a company named "Test Company" → slug "test-company"
    repo = PersistentCompanyRepository(db_session)
    company = PersistentCompany(name="Test Company", vision="v", pitch="p")
    await repo.create(company)
    # Commit so the record is visible to recover_scan's own session
    await db_session.commit()

    # Create the matching workspace folder
    company_folder = tmp_path / "test-company"
    (company_folder / "shared").mkdir(parents=True)

    import dri.orchestration.company_executor as ce_module
    original_settings = ce_module.settings

    class _FakeSettings:
        workspace_dir = tmp_path

    monkeypatch.setattr(ce_module, "settings", _FakeSettings())

    try:
        from dri.orchestration.company_executor import CompanyExecutor
        orphans = await CompanyExecutor.recover_scan()
    finally:
        monkeypatch.setattr(ce_module, "settings", original_settings)

    assert not any(o.folder_name == "test-company" for o in orphans)


@pytest.mark.asyncio
async def test_recover_scan_ignores_folders_without_shared(tmp_path, monkeypatch, db_session):
    """Folders without a shared/ subdirectory are not valid company workspaces."""
    company_folder = tmp_path / "no-shared-here"
    company_folder.mkdir()
    # No shared/ subdirectory — should not be detected

    import dri.orchestration.company_executor as ce_module
    original_settings = ce_module.settings

    class _FakeSettings:
        workspace_dir = tmp_path

    monkeypatch.setattr(ce_module, "settings", _FakeSettings())

    try:
        from dri.orchestration.company_executor import CompanyExecutor
        orphans = await CompanyExecutor.recover_scan()
    finally:
        monkeypatch.setattr(ce_module, "settings", original_settings)

    assert not any(o.folder_name == "no-shared-here" for o in orphans)
