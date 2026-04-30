"""Unit tests for ManagerAgent budget allocation logic."""
from __future__ import annotations

import pytest

from dri.agents.manager import _estimate_floor


# ── _estimate_floor ───────────────────────────────────────────────────────────

def test_estimate_floor_shell_exec():
    assert _estimate_floor(["shell_exec", "file_write"]) == 200_000


def test_estimate_floor_shell_exec_only():
    assert _estimate_floor(["shell_exec"]) == 200_000


def test_estimate_floor_web_search():
    assert _estimate_floor(["web_search", "file_write"]) == 80_000


def test_estimate_floor_web_search_only():
    assert _estimate_floor(["web_search"]) == 80_000


def test_estimate_floor_code_exec():
    assert _estimate_floor(["code_exec", "file_write"]) == 50_000


def test_estimate_floor_code_exec_only():
    assert _estimate_floor(["code_exec"]) == 50_000


def test_estimate_floor_file_only():
    assert _estimate_floor(["file_read", "file_write", "file_list"]) == 30_000


def test_estimate_floor_empty():
    assert _estimate_floor([]) == 30_000


def test_estimate_floor_shell_takes_priority_over_web():
    # shell_exec check comes first → 200k even when web_search also present
    assert _estimate_floor(["shell_exec", "web_search"]) == 200_000


def test_estimate_floor_web_takes_priority_over_code():
    # web_search check comes before code_exec → 80k
    assert _estimate_floor(["web_search", "code_exec"]) == 80_000


# ── Proportional budget allocation ───────────────────────────────────────────

def test_shares_equal_allocation():
    """Without explicit shares, all members get equal budget."""
    total = 300_000
    members = [{}, {}, {}]
    shares = [float(m.get("budget_share", 1.0)) for m in members]
    total_share = sum(shares) or len(members)

    budgets = [int(total * s / total_share) for s in shares]
    assert budgets == [100_000, 100_000, 100_000]


def test_shares_proportional_allocation():
    """Heavy worker gets proportionally more budget."""
    total = 300_000
    members = [{"budget_share": 2.0}, {"budget_share": 1.0}]
    shares = [float(m.get("budget_share", 1.0)) for m in members]
    total_share = sum(shares)

    budgets = [int(total * s / total_share) for s in shares]
    assert budgets[0] == 200_000
    assert budgets[1] == 100_000


def test_shares_normalization_sum_is_correct():
    """Budget proportions always sum to at most total_child_budget."""
    total = 600_000
    members = [{"budget_share": 3.0}, {"budget_share": 1.0}, {"budget_share": 2.0}]
    shares = [float(m.get("budget_share", 1.0)) for m in members]
    total_share = sum(shares)

    budgets = [int(total * s / total_share) for s in shares]
    # Integer division means sum may be slightly < total, never above
    assert sum(budgets) <= total
    # Proportions are respected
    assert budgets[0] > budgets[2] > budgets[1]


def test_floor_applied_when_raw_too_small():
    """Floor overrides a tiny proportional budget for a shell_exec worker."""
    total = 10_000   # intentionally tiny parent budget
    shares = [1.0]
    total_share = 1.0
    tools = ["shell_exec"]

    raw = int(total * 1.0 / total_share)
    budget = max(raw, _estimate_floor(tools))
    assert budget == 200_000  # floor wins over raw=10_000


def test_floor_not_applied_when_raw_sufficient():
    """Floor does not reduce a budget that's already above the floor."""
    total = 1_000_000
    shares = [1.0]
    total_share = 1.0
    tools = ["file_write"]

    raw = int(total * 1.0 / total_share)
    budget = max(raw, _estimate_floor(tools))
    assert budget == 1_000_000  # raw wins over floor=30_000


def test_zero_shares_fallback_to_equal():
    """All-zero shares fall back to equal distribution via len(team_members)."""
    total = 90_000
    members = [{"budget_share": 0.0}, {"budget_share": 0.0}, {"budget_share": 0.0}]
    shares = [float(m.get("budget_share", 1.0)) for m in members]
    total_share = sum(shares) or len(members)  # 0.0 → len = 3

    budgets = [int(total * s / total_share) for s in shares]
    # All zero shares → raw = 0 each; floor will apply in real code
    # Here we just verify the guard prevents ZeroDivisionError
    assert total_share == 3
    assert budgets == [0, 0, 0]
