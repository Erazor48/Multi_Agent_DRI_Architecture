"""Unit tests for core domain models."""
from __future__ import annotations

import pytest

from dri.core.models import (
    AgentConfig,
    AgentRole,
    AgentStatus,
    BudgetAllocation,
    DelegateMessage,
    EscalateMessage,
    MessageType,
    ReportMessage,
    Session,
    Skill,
    SpawnRequest,
    Task,
    TaskStatus,
)


class TestBudgetAllocation:
    def test_remaining_calculation(self):
        b = BudgetAllocation(total=1000, used=300)
        assert b.remaining == 700

    def test_fraction_remaining(self):
        b = BudgetAllocation(total=1000, used=200)
        assert b.fraction_remaining == pytest.approx(0.8)

    def test_deduct_clamps_to_total(self):
        b = BudgetAllocation(total=100, used=0)
        b.deduct(200)
        assert b.used == 100

    def test_is_depleted(self):
        b = BudgetAllocation(total=100, used=100)
        assert b.is_depleted()
        b2 = BudgetAllocation(total=100, used=99)
        assert not b2.is_depleted()

    def test_zero_total(self):
        b = BudgetAllocation(total=0, used=0)
        assert b.fraction_remaining == 0.0


class TestSkill:
    def test_to_prompt_block_structure(self):
        skill = Skill(
            name="Test Skill",
            description="A test skill",
            instructions="Do the thing",
            required_tools=["code_exec"],
        )
        block = skill.to_prompt_block()
        assert "### Skill: Test Skill" in block
        assert "A test skill" in block
        assert "Do the thing" in block


class TestTask:
    def test_complete_sets_status(self):
        task = Task(description="Do X", assigned_to="agent-1", delegated_by="agent-0")
        task.complete("Done!", 500)
        assert task.status == TaskStatus.DONE
        assert task.result == "Done!"
        assert task.tokens_used == 500
        assert task.completed_at is not None

    def test_fail_sets_status(self):
        task = Task(description="Do X", assigned_to="agent-1", delegated_by="agent-0")
        task.fail("Something broke")
        assert task.status == TaskStatus.FAILED
        assert task.error == "Something broke"


class TestMessages:
    def test_delegate_message_type(self):
        task = Task(description="Do X", assigned_to="child", delegated_by="parent")
        msg = DelegateMessage(from_agent="parent", to_agent="child", task=task)
        assert msg.type == MessageType.DELEGATE

    def test_report_message_type(self):
        msg = ReportMessage(
            from_agent="child",
            to_agent="parent",
            task_id="t1",
            result="done",
            status=TaskStatus.DONE,
            tokens_used=100,
            child_agent_id="child",
        )
        assert msg.type == MessageType.REPORT

    def test_escalate_message_type(self):
        msg = EscalateMessage(
            from_agent="child",
            to_agent="parent",
            task_id="t1",
            reason="budget_low",
            detail="20% remaining",
        )
        assert msg.type == MessageType.ESCALATE


class TestAgentConfig:
    def test_id_auto_generated(self):
        cfg = AgentConfig(
            role=AgentRole.WORKER,
            title="Test Worker",
            mission="Do stuff",
        )
        assert len(cfg.id) == 36  # UUID4 format

    def test_budget_default(self):
        cfg = AgentConfig(
            role=AgentRole.WORKER,
            title="Test Worker",
            mission="Do stuff",
        )
        assert cfg.budget.total == 0
