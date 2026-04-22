"""Unit tests for AgentRegistry."""
from __future__ import annotations

import pytest

from dri.core.models import AgentConfig, AgentRole, AgentState, AgentStatus, BudgetAllocation
from dri.core.registry import AgentRegistry


def _make_state(agent_id: str, parent_id: str | None = None, depth: int = 0) -> AgentState:
    cfg = AgentConfig(
        id=agent_id,
        role=AgentRole.WORKER if depth > 0 else AgentRole.ROOT,
        title=f"Agent {agent_id}",
        mission="Test mission",
        parent_id=parent_id,
        depth=depth,
        budget=BudgetAllocation(total=1000),
    )
    return AgentState(config=cfg, status=AgentStatus.INITIALIZING)


@pytest.mark.asyncio
async def test_register_and_get():
    reg = AgentRegistry(session_id="s1", root_agent_id="root")
    state = _make_state("root")
    await reg.register(state)
    node = reg.get_node("root")
    assert node is not None
    assert node.agent_id == "root"


@pytest.mark.asyncio
async def test_parent_child_relationship():
    reg = AgentRegistry(session_id="s1", root_agent_id="root")
    root = _make_state("root")
    child = _make_state("child", parent_id="root", depth=1)
    await reg.register(root)
    await reg.register(child)

    children = reg.get_children("root")
    assert len(children) == 1
    assert children[0].agent_id == "child"

    parent = reg.get_parent("child")
    assert parent is not None
    assert parent.agent_id == "root"


@pytest.mark.asyncio
async def test_update_status():
    reg = AgentRegistry(session_id="s1", root_agent_id="root")
    await reg.register(_make_state("root"))
    await reg.update_status("root", AgentStatus.ACTIVE)
    assert reg.get_node("root").status == AgentStatus.ACTIVE


@pytest.mark.asyncio
async def test_remove_cleans_parent():
    reg = AgentRegistry(session_id="s1", root_agent_id="root")
    await reg.register(_make_state("root"))
    await reg.register(_make_state("child", parent_id="root", depth=1))
    await reg.remove("child")

    assert reg.get_node("child") is None
    assert "child" not in reg.get_node("root").children_ids


@pytest.mark.asyncio
async def test_count_active():
    reg = AgentRegistry(session_id="s1", root_agent_id="root")
    await reg.register(_make_state("root"))
    await reg.register(_make_state("child1", parent_id="root", depth=1))
    await reg.update_status("root", AgentStatus.ACTIVE)
    await reg.update_status("child1", AgentStatus.ACTIVE)
    assert reg.count_active() == 2


@pytest.mark.asyncio
async def test_snapshot():
    reg = AgentRegistry(session_id="s1", root_agent_id="root")
    await reg.register(_make_state("root"))
    chart = reg.snapshot()
    assert chart.root_id == "root"
    assert "root" in chart.nodes
