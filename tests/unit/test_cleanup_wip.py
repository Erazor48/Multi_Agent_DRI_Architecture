"""
Tests for BaseAgent._cleanup_wip() — race condition fix (Sprint 10 P1).

Verifies that task-force workers (memory_dept set, path="" permission) only
delete their own dept's _wip/, leaving sibling workers' _wip/ intact.
"""
from __future__ import annotations

import shutil
import types
from pathlib import Path

import pytest

from dri.core.memory import ContextPacket
from dri.core.models import AgentRole, WorkspacePermission


def _make_ctx(workspace_root: str, memory_dept: str, full_access: bool) -> ContextPacket:
    """Build a minimal ContextPacket for _cleanup_wip tests."""
    if full_access:
        perms = [WorkspacePermission(path="", can_read=True, can_write=True, can_delete=True)]
    else:
        perms = [
            WorkspacePermission(path=f"{memory_dept}/", can_read=True, can_write=True, can_delete=True),
            WorkspacePermission(path="shared/", can_read=True, can_write=True, can_delete=True),
        ]
    return ContextPacket(
        agent_id="test-agent",
        title="Test Agent",
        role=AgentRole.WORKER,
        mission="test",
        parent_title="CEO",
        workspace_root=workspace_root,
        workspace_permissions=perms,
        memory_dept=memory_dept,
    )


def _invoke_cleanup(ctx: ContextPacket) -> None:
    """Call BaseAgent._cleanup_wip() via an unbound call on a mock self."""
    from dri.agents.base import BaseAgent
    mock_self = types.SimpleNamespace(_ctx=ctx)
    BaseAgent._cleanup_wip(mock_self)  # type: ignore[arg-type]


def _make_wip(root: Path, dept: str) -> Path:
    """Create a dept/_wip/ directory with a test file inside."""
    wip = root / dept / "_wip"
    wip.mkdir(parents=True, exist_ok=True)
    (wip / "draft.txt").write_text("in progress")
    return wip


# ── P1: task-force worker with memory_dept set should NOT delete sibling _wip/ ──

def test_cleanup_wip_task_force_worker_only_cleans_own_dept(tmp_path):
    wip_a = _make_wip(tmp_path, "dept-a")
    wip_b = _make_wip(tmp_path, "dept-b")

    ctx = _make_ctx(str(tmp_path), memory_dept="dept-a", full_access=True)
    _invoke_cleanup(ctx)

    assert not wip_a.exists(), "Worker A must delete its own _wip/"
    assert wip_b.exists(), "Worker A must NOT delete Worker B's _wip/"


def test_cleanup_wip_synthesizer_cleans_all_wip(tmp_path):
    """Synthesizer/manager (memory_dept='') with full access cleans all _wip/ dirs."""
    wip_a = _make_wip(tmp_path, "dept-a")
    wip_b = _make_wip(tmp_path, "dept-b")

    ctx = _make_ctx(str(tmp_path), memory_dept="", full_access=True)
    _invoke_cleanup(ctx)

    assert not wip_a.exists(), "Synthesizer must delete dept-a _wip/"
    assert not wip_b.exists(), "Synthesizer must delete dept-b _wip/"


def test_cleanup_wip_normal_rbac_cleans_own_dept_only(tmp_path):
    """Normal RBAC (specific path permission) cleans only own dept _wip/."""
    wip_a = _make_wip(tmp_path, "dept-a")
    wip_b = _make_wip(tmp_path, "dept-b")

    ctx = _make_ctx(str(tmp_path), memory_dept="dept-a", full_access=False)
    _invoke_cleanup(ctx)

    assert not wip_a.exists(), "Normal RBAC agent must delete its own _wip/"
    assert wip_b.exists(), "Normal RBAC agent must NOT delete other depts' _wip/"


def test_cleanup_wip_no_workspace_root():
    """No workspace root — nothing happens, no error."""
    ctx = ContextPacket(
        agent_id="x",
        title="X",
        role=AgentRole.WORKER,
        mission="x",
        parent_title="CEO",
        workspace_root="",
    )
    _invoke_cleanup(ctx)  # should not raise


def test_cleanup_wip_missing_wip_dir(tmp_path):
    """Dept exists but no _wip/ dir — no error."""
    (tmp_path / "dept-a").mkdir()
    ctx = _make_ctx(str(tmp_path), memory_dept="dept-a", full_access=True)
    _invoke_cleanup(ctx)  # should not raise
