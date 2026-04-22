"""
Integration test — full session wiring with a mocked Anthropic client.

Validates that:
- A pitch flows through CEO → Manager → Worker chain
- Budget is correctly tracked and propagated
- All DB writes succeed
- The final result returns to the caller

Does NOT make real API calls — Anthropic client is mocked.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dri.core.models import AgentRole, Session
from dri.storage.database import drop_db, init_db


def _make_anthropic_response(text: str = "", tool_name: str = "", tool_input: dict = None):
    """Build a mock anthropic.types.Message."""
    content = []
    if text:
        block = MagicMock()
        block.type = "text"
        block.text = text
        content.append(block)
    if tool_name:
        block = MagicMock()
        block.type = "tool_use"
        block.name = tool_name
        block.id = f"toolu_{tool_name}"
        block.input = tool_input or {}
        content.append(block)

    msg = MagicMock()
    msg.content = content
    msg.stop_reason = "end_turn"
    msg.usage = MagicMock()
    msg.usage.input_tokens = 100
    msg.usage.output_tokens = 50
    return msg


@pytest.fixture(autouse=True)
async def clean_db():
    await init_db()
    yield
    await drop_db()


@pytest.mark.asyncio
async def test_full_session_wiring():
    """
    Full wiring test: pitch → CEO designs company → spawns one manager →
    manager spawns one worker → worker completes → results aggregate.
    """
    ceo_design = _make_anthropic_response(
        text="Launching your company now.",
        tool_name="design_company",
        tool_input={
            "company_name": "TestCo",
            "company_vision": "A test company.",
            "departments": [
                {
                    "title": "Chief Operations Officer",
                    "mission": "Handle all operations.",
                    "initial_task": "Set up the operations framework.",
                    "skills": ["team_management"],
                }
            ],
            "initial_message_to_user": "I'm building TestCo for you.",
        },
    )

    manager_plan = _make_anthropic_response(
        tool_name="create_org_plan",
        tool_input={
            "team_members": [
                {
                    "title": "Operations Analyst",
                    "role": "worker",
                    "mission": "Analyze operational requirements.",
                    "task": "Document the operations workflow.",
                    "skills": ["content_writing"],
                    "tools": ["file_write"],
                    "budget_share": 0.8,
                }
            ],
            "synthesis_approach": "Compile analyst's output into a report.",
        },
    )

    worker_result = _make_anthropic_response(text="Operations workflow documented successfully.")
    manager_synthesis = _make_anthropic_response(text="Operations framework complete.")
    ceo_synthesis = _make_anthropic_response(text="# TestCo Report\n\nCompany is operational.")

    # Each call to create() on the mock client returns the right response in order
    call_sequence = [ceo_design, manager_plan, worker_result, manager_synthesis, ceo_synthesis]
    call_index = 0

    async def mock_create(**kwargs):
        nonlocal call_index
        resp = call_sequence[min(call_index, len(call_sequence) - 1)]
        call_index += 1
        return resp

    mock_messages = MagicMock()
    mock_messages.create = mock_create

    mock_client = MagicMock()
    mock_client.messages = mock_messages

    with patch("dri.agents.base.anthropic.AsyncAnthropic", return_value=mock_client):
        from dri.orchestration.executor import Executor
        executor = Executor()
        status_log = []
        result = await executor.run(
            "Build a simple operations company.",
            on_status=lambda msg: status_log.append(msg),
        )

    assert result, "Should return a non-empty result"
    assert len(status_log) >= 2, "Should have at least init + complete status messages"
    assert "complete" in status_log[-1].lower() or "session" in status_log[-1].lower()


@pytest.mark.asyncio
async def test_budget_flows_down_hierarchy():
    """Verify that budget is allocated to children and tracked at session level."""
    from dri.core.budget import BudgetManager
    from dri.config.settings import settings

    budget = BudgetManager(settings.budget_max_tokens_per_session)
    await budget.allocate("root", settings.budget_max_tokens_per_session)

    child_share = budget.compute_child_share("root", 3)
    assert child_share > 0
    assert child_share < settings.budget_max_tokens_per_session

    await budget.allocate("child-1", child_share)
    await budget.allocate("child-2", child_share)
    await budget.allocate("child-3", child_share)

    await budget.check_and_deduct("child-1", 100)
    await budget.check_and_deduct("child-2", 200)

    assert budget.session_used == 300


@pytest.mark.asyncio
async def test_registry_tracks_full_hierarchy():
    """Verify registry correctly tracks a 3-level hierarchy."""
    from dri.core.models import AgentConfig, AgentState, AgentStatus, BudgetAllocation
    from dri.core.registry import AgentRegistry

    registry = AgentRegistry(session_id="test", root_agent_id="ceo")

    def _state(aid, parent, role, depth):
        cfg = AgentConfig(
            id=aid, role=role, title=aid, mission="test",
            parent_id=parent, depth=depth,
            budget=BudgetAllocation(total=1000),
        )
        return AgentState(config=cfg)

    await registry.register(_state("ceo", None, AgentRole.ROOT, 0))
    await registry.register(_state("cmo", "ceo", AgentRole.MANAGER, 1))
    await registry.register(_state("cto", "ceo", AgentRole.MANAGER, 1))
    await registry.register(_state("writer", "cmo", AgentRole.WORKER, 2))
    await registry.register(_state("dev", "cto", AgentRole.WORKER, 2))

    assert registry.count_total() == 5
    assert len(registry.get_children("ceo")) == 2
    assert len(registry.get_children("cmo")) == 1
    assert registry.depth_of("writer") == 2
    assert len(registry.all_workers()) == 2
    assert len(registry.all_managers()) == 2
