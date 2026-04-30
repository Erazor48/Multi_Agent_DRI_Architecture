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


# ─── Budget borrowing ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_return_unused_gives_back_remaining(budget):
    await budget.allocate("worker", 5_000)
    await budget.check_and_deduct("worker", 1_000)
    unused = await budget.return_unused("worker")
    assert unused == 4_000


@pytest.mark.asyncio
async def test_return_unused_zeroes_remaining(budget):
    await budget.allocate("worker", 5_000)
    await budget.check_and_deduct("worker", 2_000)
    await budget.return_unused("worker")
    alloc = budget.get_allocation("worker")
    assert alloc.remaining == 0
    assert alloc.used == 2_000  # used is preserved


@pytest.mark.asyncio
async def test_return_unused_missing_agent_returns_zero(budget):
    result = await budget.return_unused("ghost")
    assert result == 0


@pytest.mark.asyncio
async def test_add_to_allocation_increases_total(budget):
    await budget.allocate("worker", 5_000)
    await budget.add_to_allocation("worker", 3_000)
    alloc = budget.get_allocation("worker")
    assert alloc.total == 8_000
    assert alloc.remaining == 8_000  # none used yet


@pytest.mark.asyncio
async def test_add_to_allocation_missing_agent_is_noop(budget):
    await budget.add_to_allocation("ghost", 9_999)  # must not raise


@pytest.mark.asyncio
async def test_add_zero_is_noop(budget):
    await budget.allocate("worker", 5_000)
    await budget.add_to_allocation("worker", 0)
    alloc = budget.get_allocation("worker")
    assert alloc.total == 5_000


@pytest.mark.asyncio
async def test_borrow_redistribute_pattern(budget):
    """Typical pattern: pool from completed workers, add to a budget-failed worker."""
    await budget.allocate("worker-done", 50_000)
    await budget.allocate("worker-failed", 10_000)

    # worker-done used 15k of 50k → 35k unused
    await budget.check_and_deduct("worker-done", 15_000)
    pool = await budget.return_unused("worker-done")
    assert pool == 35_000

    # Give pool to failed worker
    await budget.add_to_allocation("worker-failed", pool)
    failed_alloc = budget.get_allocation("worker-failed")
    assert failed_alloc.total == 45_000  # 10k + 35k
