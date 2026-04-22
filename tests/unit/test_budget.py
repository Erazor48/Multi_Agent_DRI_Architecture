"""Unit tests for the budget manager."""
from __future__ import annotations

import pytest
import pytest_asyncio

from dri.core.budget import BudgetExceededError, BudgetManager, BudgetWarning


@pytest.fixture
def budget():
    return BudgetManager(session_budget=10_000)


@pytest.mark.asyncio
async def test_allocate_and_check(budget):
    await budget.allocate("agent-1", 5000)
    alloc = budget.get_allocation("agent-1")
    assert alloc is not None
    assert alloc.total == 5000
    assert alloc.remaining == 5000


@pytest.mark.asyncio
async def test_check_and_deduct_reduces_budget(budget):
    await budget.allocate("agent-1", 5000)
    await budget.check_and_deduct("agent-1", 1000)
    alloc = budget.get_allocation("agent-1")
    assert alloc.used == 1000


@pytest.mark.asyncio
async def test_budget_exceeded_raises(budget):
    await budget.allocate("agent-1", 100)
    # Drain it
    await budget.check_and_deduct("agent-1", 100)
    with pytest.raises(BudgetExceededError):
        await budget.check_and_deduct("agent-1", 1)


@pytest.mark.asyncio
async def test_budget_warning_raised_below_threshold(budget):
    await budget.allocate("agent-1", 1000)
    # Spending 850 of 1000 leaves 15% → below the 20% threshold → raises BudgetWarning
    with pytest.raises(BudgetWarning):
        await budget.check_and_deduct("agent-1", 850)


@pytest.mark.asyncio
async def test_untracked_agent_passes_without_error(budget):
    # Agents not registered are allowed through (root pre-registration)
    await budget.check_and_deduct("unknown-agent", 1000)  # should not raise


@pytest.mark.asyncio
async def test_session_totals(budget):
    await budget.allocate("a1", 3000)
    await budget.allocate("a2", 3000)
    await budget.check_and_deduct("a1", 500)
    await budget.check_and_deduct("a2", 300)
    assert budget.session_used == 800
    assert budget.session_remaining == 10_000 - 800


@pytest.mark.asyncio
async def test_child_share_computation(budget):
    await budget.allocate("parent", 10_000)
    share = budget.compute_child_share("parent", 4)
    assert share > 0
    assert share <= 10_000
