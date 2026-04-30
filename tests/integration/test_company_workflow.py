"""
Integration tests for the CompanyExecutor workflow.

Tests cover:
1. CompanyExecutor.create() — company persisted in DB + workspace dirs created
2. CompanyExecutor.chat() — CEO responds with text (no spawn)
3. Layer 6 — _company_history.md appended after a task
4. Layer 2 — AgentMemory.for_agent() reads expertise/feedback from disk
5. _build_ceo_messages() — NEW CONVERSATION marker injected on first message

All LLM calls are mocked — no real API keys required.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

# conftest provides MockLLMProvider, make_tool_response, make_text_response


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def reset_db():
    """Fresh in-memory DB for every test."""
    from dri.storage.database import drop_db, init_db
    await init_db()
    yield
    await drop_db()


# ─── 1. CompanyExecutor.create() ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_persists_company_in_db(tmp_path):
    """create() calls design_company tool → company row in DB, workspace dirs exist."""
    from dri.orchestration.company_executor import CompanyExecutor
    from dri.storage.database import get_session
    from dri.storage.repositories import PersistentCompanyRepository
    from tests.conftest import MockLLMProvider, make_tool_response

    design_response = make_tool_response("design_company", {
        "company_name": "IntegCo",
        "company_vision": "Build integrated solutions",
        "departments": [
            {"title": "Engineering", "mission": "Build products"},
            {"title": "Marketing", "mission": "Grow brand"},
        ],
    })
    mock_provider = MockLLMProvider([design_response])

    with patch("dri.orchestration.company_executor.create_provider", return_value=mock_provider), \
         patch("dri.config.settings.settings.workspace_dir", tmp_path):
        company = await CompanyExecutor.create(pitch="Build integrated solutions for SMBs")

    assert company.name == "IntegCo"
    assert len(company.org_structure) == 2

    # DB row exists
    async with get_session() as db:
        repo = PersistentCompanyRepository(db)
        persisted = await repo.get(company.id)
    assert persisted is not None
    assert persisted.name == "IntegCo"


@pytest.mark.asyncio
async def test_create_builds_workspace_dirs(tmp_path):
    """create() creates shared/, ceo/, and one dir per department."""
    from dri.orchestration.company_executor import CompanyExecutor
    from tests.conftest import MockLLMProvider, make_tool_response

    design_response = make_tool_response("design_company", {
        "company_name": "DirTestCo",
        "company_vision": "Test dirs",
        "departments": [
            {"title": "Alpha Team", "mission": "Do alpha things"},
        ],
    })
    mock_provider = MockLLMProvider([design_response])

    with patch("dri.orchestration.company_executor.create_provider", return_value=mock_provider), \
         patch("dri.config.settings.settings.workspace_dir", tmp_path):
        company = await CompanyExecutor.create(pitch="Test company for directory creation")

    ws = tmp_path / "dirtestco"
    assert (ws / "shared").is_dir()
    assert (ws / "ceo").is_dir()
    assert (ws / "alpha-team").is_dir()


@pytest.mark.asyncio
async def test_create_raises_if_llm_does_not_call_tool(tmp_path):
    """create() raises ValueError when LLM returns text instead of design_company call."""
    from dri.orchestration.company_executor import CompanyExecutor
    from tests.conftest import MockLLMProvider, make_text_response

    text_only = make_text_response("Here is my plan... (forgot to call tool)")
    mock_provider = MockLLMProvider([text_only])

    with patch("dri.orchestration.company_executor.create_provider", return_value=mock_provider), \
         patch("dri.config.settings.settings.workspace_dir", tmp_path):
        with pytest.raises(ValueError, match="design_company"):
            await CompanyExecutor.create(pitch="A company")


# ─── 2. CompanyExecutor.chat() ───────────────────────────────────────────────

@pytest_asyncio.fixture
async def persisted_company(tmp_path):
    """Create a minimal company directly in DB (no LLM needed)."""
    from dri.core.models import PersistentCompany
    from dri.storage.database import get_session
    from dri.storage.repositories import PersistentCompanyRepository

    company = PersistentCompany(
        name="ChatCo",
        vision="Test chat",
        pitch="A company for chat tests",
        org_structure=[{"title": "Engineering", "mission": "Build things"}],
    )
    async with get_session() as db:
        repo = PersistentCompanyRepository(db)
        await repo.create(company)

    # Create minimal workspace
    ws = tmp_path / "chatco"
    (ws / "shared").mkdir(parents=True)
    (ws / "ceo").mkdir()

    return company, ws


@pytest.mark.asyncio
async def test_chat_returns_ceo_text_response(persisted_company, tmp_path):
    """chat() returns the CEO's text response when no tool call is made."""
    company, ws = persisted_company
    from dri.orchestration.company_executor import CompanyExecutor
    from tests.conftest import MockLLMProvider, make_text_response

    ceo_text = "Hello founder! Welcome to ChatCo. How can I help you today?"
    # Two create_provider calls: one for summary check, one for CEO loop
    mock_summary = MockLLMProvider([])  # no summarization on empty history
    mock_ceo = MockLLMProvider([make_text_response(ceo_text)])

    def _provider_factory():
        # First call → summary provider, second → CEO provider
        if not hasattr(_provider_factory, "_count"):
            _provider_factory._count = 0
        _provider_factory._count += 1
        return mock_summary if _provider_factory._count == 1 else mock_ceo

    with patch("dri.orchestration.company_executor.create_provider", side_effect=_provider_factory), \
         patch("dri.config.settings.settings.workspace_dir", tmp_path):
        response = await CompanyExecutor.chat(company_id=company.id, user_message="Hello!")

    assert ceo_text in response


@pytest.mark.asyncio
async def test_chat_saves_user_and_ceo_messages(persisted_company, tmp_path):
    """chat() persists user + CEO messages in DB."""
    company, ws = persisted_company
    from dri.orchestration.company_executor import CompanyExecutor
    from dri.storage.database import get_session
    from dri.storage.repositories import CompanyMessageRepository
    from tests.conftest import MockLLMProvider, make_text_response

    mock_summary = MockLLMProvider([])
    mock_ceo = MockLLMProvider([make_text_response("Got it, founder!")])

    call_n = [0]

    def _factory():
        call_n[0] += 1
        return mock_summary if call_n[0] == 1 else mock_ceo

    with patch("dri.orchestration.company_executor.create_provider", side_effect=_factory), \
         patch("dri.config.settings.settings.workspace_dir", tmp_path):
        await CompanyExecutor.chat(company_id=company.id, user_message="What are our priorities?")

    async with get_session() as db:
        repo = CompanyMessageRepository(db)
        msgs = await repo.list_by_company(company.id)

    roles = [m.role for m in msgs]
    assert "user" in roles
    assert "ceo" in roles


# ─── 3. Layer 6 — _company_history.md ────────────────────────────────────────

@pytest.mark.asyncio
async def test_append_company_history_creates_file(tmp_path):
    """_append_company_history() creates shared/_company_history.md with task entry."""
    from dri.core.models import PersistentCompany, TaskStatus
    from dri.orchestration.company_executor import _append_company_history

    company = PersistentCompany(
        name="HistoryCo", vision="v", pitch="p", org_structure=[]
    )

    # Mock registry with no workers/managers
    registry = MagicMock()
    registry.all_workers.return_value = []
    registry.all_managers.return_value = []

    report = MagicMock()
    report.status = TaskStatus.DONE

    (tmp_path / "shared").mkdir()

    _append_company_history(
        workspace_root=str(tmp_path),
        task_description="Build a landing page for HistoryCo",
        registry=registry,
        report=report,
        tokens_total=8500,
    )

    history_file = tmp_path / "shared" / "_company_history.md"
    assert history_file.exists()
    content = history_file.read_text(encoding="utf-8")
    assert "Build a landing page" in content
    assert "8,500" in content
    assert "DONE" in content


@pytest.mark.asyncio
async def test_append_company_history_accumulates(tmp_path):
    """Multiple calls append separate entries."""
    from dri.core.models import PersistentCompany, TaskStatus
    from dri.orchestration.company_executor import _append_company_history

    company = PersistentCompany(name="AccumCo", vision="v", pitch="p", org_structure=[])
    registry = MagicMock()
    registry.all_workers.return_value = []
    registry.all_managers.return_value = []
    report = MagicMock()
    report.status = TaskStatus.DONE

    (tmp_path / "shared").mkdir()

    _append_company_history(
        workspace_root=str(tmp_path),
        task_description="Task one",
        registry=registry,
        report=report,
        tokens_total=1000,
    )
    _append_company_history(
        workspace_root=str(tmp_path),
        task_description="Task two",
        registry=registry,
        report=report,
        tokens_total=2000,
    )

    content = (tmp_path / "shared" / "_company_history.md").read_text()
    assert "Task one" in content
    assert "Task two" in content


# ─── 4. Layer 2 — AgentMemory.for_agent() ────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_memory_reads_expertise_and_feedback(tmp_path):
    """AgentMemory.for_agent() + load() returns expertise + feedback from disk."""
    from dri.core.memory import AgentMemory

    dept = "engineering"
    slug = "backend-developer"
    base = tmp_path / dept / "_knowledge" / slug
    base.mkdir(parents=True)

    (base / "expertise.md").write_text("## Domain Expertise\nUse async for all I/O.", encoding="utf-8")
    (base / "feedback.md").write_text("## Feedback\nGreat error handling. Improve test coverage.", encoding="utf-8")

    memory_obj = AgentMemory.for_agent(
        workspace_root=str(tmp_path),
        workspace_permissions=[],
        title="Backend Developer",
        memory_dept=dept,
    )

    assert memory_obj is not None
    content = memory_obj.load()
    assert "Use async for all I/O" in content
    assert "Great error handling" in content


@pytest.mark.asyncio
async def test_agent_memory_returns_none_when_no_dept(tmp_path):
    """AgentMemory.for_agent() returns None when no dept can be determined."""
    from dri.core.memory import AgentMemory

    mem = AgentMemory.for_agent(
        workspace_root=str(tmp_path),
        workspace_permissions=[],  # empty perms + no memory_dept → None
        title="Unknown Agent",
        memory_dept="",
    )

    assert mem is None


@pytest.mark.asyncio
async def test_agent_memory_empty_load_when_no_files(tmp_path):
    """AgentMemory.load() returns empty string when knowledge dir exists but has no files."""
    from dri.core.memory import AgentMemory

    memory_obj = AgentMemory.for_agent(
        workspace_root=str(tmp_path),
        workspace_permissions=[],
        title="New Agent",
        memory_dept="engineering",
    )

    assert memory_obj is not None
    content = memory_obj.load()
    assert content == ""


# ─── 5. _build_ceo_messages() — NEW CONVERSATION marker ──────────────────────

def test_build_ceo_messages_injects_new_conversation_marker_on_first_message():
    """Empty history → [NEW CONVERSATION] prefix injected in the final user message."""
    from dri.orchestration.company_executor import _build_ceo_messages

    msgs = _build_ceo_messages(history=[], current_user_message="Bonjour!")
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    assert "[NEW CONVERSATION" in msgs[0]["content"]
    assert "Bonjour!" in msgs[0]["content"]


def test_build_ceo_messages_no_marker_with_existing_history():
    """Non-empty history → no [NEW CONVERSATION] marker injected."""
    from dri.core.models import CompanyMessage
    from dri.orchestration.company_executor import _build_ceo_messages

    history = [
        CompanyMessage(company_id="c1", role="user", content="First message"),
        CompanyMessage(company_id="c1", role="ceo", content="CEO reply"),
    ]
    msgs = _build_ceo_messages(history=history, current_user_message="Follow-up")
    last = msgs[-1]
    assert "[NEW CONVERSATION" not in last["content"]
    assert "Follow-up" in last["content"]


def test_build_ceo_messages_summary_prepended_to_first_user():
    """Summary record is prepended to the first user message in the window."""
    from dri.core.models import CompanyMessage
    from dri.orchestration.company_executor import _build_ceo_messages

    summary = CompanyMessage(company_id="c1", role="summary", content="## Summary\nWe built X.")
    user_msg = CompanyMessage(company_id="c1", role="user", content="What next?")
    ceo_msg = CompanyMessage(company_id="c1", role="ceo", content="Next step is Y.")

    history = [summary, user_msg, ceo_msg]
    msgs = _build_ceo_messages(history=history, current_user_message="Continue")

    # First actual user message should contain the summary
    first_user = next(m for m in msgs if m["role"] == "user")
    assert "## Summary" in first_user["content"]
    assert "We built X." in first_user["content"]


# ─── 6. Budget borrowing integration ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_budget_borrow_pool_and_redistribute():
    """
    Pool unused tokens from a completed worker and add them to a second agent.
    Verifies return_unused zeroes remaining and add_to_allocation increases total.
    """
    from dri.core.budget import BudgetManager

    mgr = BudgetManager(session_budget=200_000)
    await mgr.allocate("worker-a", 50_000)
    await mgr.allocate("worker-b", 30_000)

    # worker-a uses 10k out of 50k → 40k unused
    await mgr.check_and_deduct("worker-a", 10_000)

    # Pool from worker-a
    unused = await mgr.return_unused("worker-a")
    assert unused == 40_000

    # worker-a remaining is now 0
    alloc_a = mgr.get_allocation("worker-a")
    assert alloc_a.remaining == 0
    assert alloc_a.used == 10_000

    # Add to worker-b
    await mgr.add_to_allocation("worker-b", unused)
    alloc_b = mgr.get_allocation("worker-b")
    assert alloc_b.total == 30_000 + 40_000


@pytest.mark.asyncio
async def test_return_unused_on_missing_agent():
    """return_unused for an unregistered agent returns 0 without error."""
    from dri.core.budget import BudgetManager

    mgr = BudgetManager(session_budget=100_000)
    result = await mgr.return_unused("nonexistent-agent")
    assert result == 0


@pytest.mark.asyncio
async def test_add_to_allocation_noop_on_missing_agent():
    """add_to_allocation for an unregistered agent is a no-op."""
    from dri.core.budget import BudgetManager

    mgr = BudgetManager(session_budget=100_000)
    await mgr.add_to_allocation("nonexistent-agent", 5000)  # should not raise
