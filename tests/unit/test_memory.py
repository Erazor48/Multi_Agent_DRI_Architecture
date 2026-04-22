"""Unit tests for the memory / context injection system."""
from __future__ import annotations

import pytest

from dri.core.memory import ContextBuilder, ContextPacket
from dri.core.models import AgentConfig, AgentRole, BudgetAllocation, Skill, Task, TaskStatus


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
