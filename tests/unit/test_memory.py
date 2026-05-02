"""Unit tests for the memory / context injection system."""
from __future__ import annotations

import pytest

from dri.core.memory import AgentMemory, ContextBuilder, ContextPacket
from dri.core.models import AgentConfig, AgentRole, BudgetAllocation, Skill, Task, TaskStatus, WorkspacePermission


@pytest.fixture
def sample_config():
    return AgentConfig(
        role=AgentRole.WORKER,
        title="Content Writer",
        mission="Write blog posts about AI.",
        skills=[
            Skill(
                name="Content Writing",
                description="Write high-quality content.",
                instructions="Follow SEO best practices.",
            )
        ],
        allowed_tools=["file_write"],
        budget=BudgetAllocation(total=50_000),
    )


def test_context_packet_to_system_prompt(sample_config):
    packet = ContextBuilder.build(
        child_config=sample_config,
        parent_title="CMO",
        company_name="TechBlog Inc",
        company_pitch="A blog about AI",
    )
    prompt = packet.to_system_prompt()

    assert "Content Writer" in prompt
    assert "CMO" in prompt
    assert "TechBlog Inc" in prompt
    assert "Content Writing" in prompt
    assert "50,000" in prompt


def test_context_packet_includes_constraints(sample_config):
    packet = ContextBuilder.build(
        child_config=sample_config,
        parent_title="CMO",
        company_name="X",
        company_pitch="Y",
        constraints=["Never write more than 1000 words.", "Always include sources."],
    )
    prompt = packet.to_system_prompt()
    assert "Never write more than 1000 words." in prompt
    assert "Always include sources." in prompt


def test_context_packet_includes_prior_results(sample_config):
    packet = ContextBuilder.build(
        child_config=sample_config,
        parent_title="CMO",
        company_name="X",
        company_pitch="Y",
        prior_results=["Previous article: AI in 2025 — summary here."],
    )
    prompt = packet.to_system_prompt()
    assert "Previous article" in prompt


def test_summarize_task_result_done():
    task = Task(
        description="Research competitors",
        assigned_to="a1",
        delegated_by="a0",
        status=TaskStatus.DONE,
        result="Found 5 competitors: X, Y, Z...",
    )
    summary = ContextBuilder.summarize_task_result(task)
    assert "Research competitors" in summary
    assert "Found 5 competitors" in summary


def test_summarize_task_result_no_result():
    task = Task(
        description="Research competitors",
        assigned_to="a1",
        delegated_by="a0",
    )
    summary = ContextBuilder.summarize_task_result(task)
    assert "no result" in summary.lower()


# ── Layer 2 memory_dept fix — task-force mode ──────────────────────────────


def test_agent_memory_for_agent_with_explicit_memory_dept(tmp_path):
    """Task-force agents receive path='' perms. memory_dept must override perm scan."""
    full_access_perm = WorkspacePermission(path="", can_read=True, can_write=True, can_delete=True)
    mem = AgentMemory.for_agent(
        workspace_root=str(tmp_path),
        workspace_permissions=[full_access_perm],
        title="SEO Specialist",
        memory_dept="chief-marketing-officer",
    )
    assert mem is not None
    expected = tmp_path / "chief-marketing-officer" / "_knowledge" / "seo-specialist"
    assert mem.path == expected
    assert expected.exists()


def test_agent_memory_for_agent_fallback_to_permissions(tmp_path):
    """One-shot mode: no memory_dept, specific dept perm is used as fallback."""
    dept_perm = WorkspacePermission(
        path="chief-marketing-officer/", can_read=True, can_write=True, can_delete=True
    )
    mem = AgentMemory.for_agent(
        workspace_root=str(tmp_path),
        workspace_permissions=[dept_perm],
        title="SEO Specialist",
    )
    assert mem is not None
    expected = tmp_path / "chief-marketing-officer" / "_knowledge" / "seo-specialist"
    assert mem.path == expected


def test_agent_memory_for_agent_no_dept_returns_none(tmp_path):
    """No memory_dept and only empty/shared perms → returns None (unchanged behaviour)."""
    perms = [
        WorkspacePermission(path="", can_read=True, can_write=True, can_delete=True),
        WorkspacePermission(path="shared/", can_read=True, can_write=True, can_delete=True),
    ]
    mem = AgentMemory.for_agent(
        workspace_root=str(tmp_path),
        workspace_permissions=perms,
        title="SEO Specialist",
    )
    assert mem is None


def test_context_builder_propagates_memory_dept(sample_config):
    """ContextBuilder.build() must forward memory_dept to the ContextPacket."""
    packet = ContextBuilder.build(
        child_config=sample_config,
        parent_title="CMO",
        company_name="X",
        company_pitch="Y",
        memory_dept="chief-marketing-officer",
    )
    assert packet.memory_dept == "chief-marketing-officer"


def test_context_builder_memory_dept_defaults_to_empty(sample_config):
    """Omitting memory_dept keeps the field empty (backwards compatible)."""
    packet = ContextBuilder.build(
        child_config=sample_config,
        parent_title="CMO",
        company_name="X",
        company_pitch="Y",
    )
    assert packet.memory_dept == ""


# ── Worker prompt condensation (Sprint 6) ─────────────────────────────────


def _make_config(role: AgentRole) -> AgentConfig:
    return AgentConfig(
        role=role,
        title="Dev" if role == AgentRole.WORKER else "CTO",
        mission="Build things.",
        allowed_tools=["file_write"],
        budget=BudgetAllocation(total=50_000),
    )


def test_worker_prompt_shorter_than_manager():
    """Workers get a condensed Rules block; managers get the full version."""
    long_kb = "A" * 3000
    long_hist = "B" * 2000

    worker_packet = ContextBuilder.build(
        child_config=_make_config(AgentRole.WORKER),
        parent_title="CTO",
        company_name="TestCo",
        company_pitch="test",
        company_kb=long_kb,
        company_history_snippet=long_hist,
    )
    manager_packet = ContextBuilder.build(
        child_config=_make_config(AgentRole.MANAGER),
        parent_title="CEO",
        company_name="TestCo",
        company_pitch="test",
        company_kb=long_kb,
        company_history_snippet=long_hist,
    )

    worker_prompt = worker_packet.to_system_prompt()
    manager_prompt = manager_packet.to_system_prompt()

    assert len(worker_prompt) < len(manager_prompt), (
        f"Worker prompt ({len(worker_prompt)}) should be shorter than manager prompt ({len(manager_prompt)})"
    )


def test_worker_kb_truncated_at_1500():
    """Workers see at most 1500 chars of the company KB (truncation marker present)."""
    long_kb = "K" * 3000
    worker_packet = ContextBuilder.build(
        child_config=_make_config(AgentRole.WORKER),
        parent_title="CTO",
        company_name="TestCo",
        company_pitch="test",
        company_kb=long_kb,
    )
    prompt = worker_packet.to_system_prompt()
    assert "[...truncated]" in prompt, "Worker KB should include truncation marker"


def test_manager_kb_not_truncated():
    """Managers receive the full KB without truncation."""
    long_kb = "K" * 3000
    manager_packet = ContextBuilder.build(
        child_config=_make_config(AgentRole.MANAGER),
        parent_title="CEO",
        company_name="TestCo",
        company_pitch="test",
        company_kb=long_kb,
    )
    prompt = manager_packet.to_system_prompt()
    assert prompt.count("K") >= 3000
