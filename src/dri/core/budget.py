"""
Budget management — token tracking and enforcement.
Every LLM call goes through BudgetManager.check_and_deduct() before executing.
"""
from __future__ import annotations

import asyncio

from dri.config.settings import settings
from dri.core.models import BudgetAllocation


class BudgetExceededError(Exception):
    """Raised when an agent has no budget left for an LLM call."""

    def __init__(self, agent_id: str, requested: int, remaining: int) -> None:
        self.agent_id = agent_id
        self.requested = requested
        self.remaining = remaining
        super().__init__(
            f"Agent {agent_id} requested {requested} tokens but only {remaining} remain."
        )


class BudgetWarning(Exception):
    """Raised (then caught by BaseAgent) when budget drops below warning threshold."""

    def __init__(self, agent_id: str, fraction_remaining: float) -> None:
        self.agent_id = agent_id
        self.fraction_remaining = fraction_remaining
        super().__init__(
            f"Agent {agent_id} budget at {fraction_remaining:.1%} — escalating to parent."
        )


class BudgetManager:
    """
    Session-scoped budget tracker.

    One BudgetManager per session, shared across all agents in the session.
    Each agent has its own allocation (total + used), stored here and mirrored to DB
    by the calling code (BaseAgent deducts from DB after each LLM call).
    """

    def __init__(self, session_budget: int) -> None:
        self._session_budget = session_budget
        self._session_used = 0
        self._allocations: dict[str, BudgetAllocation] = {}
        self._lock = asyncio.Lock()

    # ──────────────────────────────────────────────────────────
    # Allocation
    # ──────────────────────────────────────────────────────────

    async def allocate(self, agent_id: str, tokens: int) -> BudgetAllocation:
        """Register a new agent with a token allocation."""
        allocation = BudgetAllocation(total=tokens, used=0)
        async with self._lock:
            self._allocations[agent_id] = allocation
        return allocation

    def compute_child_share(self, parent_id: str, num_children: int) -> int:
        """
        Compute how many tokens each child of parent_id should receive.
        Uses the configured share fraction, split evenly across children.
        """
        parent_alloc = self._allocations.get(parent_id)
        if parent_alloc is None or num_children == 0:
            return 0
        share_per_child = int(
            parent_alloc.remaining * settings.budget_child_default_share / num_children
        )
        return max(share_per_child, 1000)  # floor: 1k tokens minimum per child

    # ──────────────────────────────────────────────────────────
    # Enforcement
    # ──────────────────────────────────────────────────────────

    async def check_and_deduct(self, agent_id: str, estimated_tokens: int) -> None:
        """
        Call before every LLM request.
        Raises BudgetExceededError if the agent is out of tokens.
        Raises BudgetWarning if below warning threshold (caller should escalate, then continue).
        """
        async with self._lock:
            alloc = self._allocations.get(agent_id)
            if alloc is None:
                return  # untracked agent (root before allocation) — allow

            if alloc.is_depleted():
                raise BudgetExceededError(agent_id, estimated_tokens, 0)

            alloc.deduct(estimated_tokens)
            self._session_used += estimated_tokens

            if (
                not alloc.is_depleted()
                and alloc.fraction_remaining < settings.budget_warning_threshold
            ):
                raise BudgetWarning(agent_id, alloc.fraction_remaining)

    async def record_actual(self, agent_id: str, estimated: int, actual: int) -> None:
        """Adjust after we know the real token count (API response)."""
        diff = actual - estimated
        if diff == 0:
            return
        async with self._lock:
            alloc = self._allocations.get(agent_id)
            if alloc:
                alloc.deduct(diff)  # positive diff = over-estimate correction
            self._session_used += diff

    # ──────────────────────────────────────────────────────────
    # Reads
    # ──────────────────────────────────────────────────────────

    def get_allocation(self, agent_id: str) -> BudgetAllocation | None:
        return self._allocations.get(agent_id)

    @property
    def session_used(self) -> int:
        return self._session_used

    @property
    def session_remaining(self) -> int:
        return max(0, self._session_budget - self._session_used)

    @property
    def session_fraction_remaining(self) -> float:
        if self._session_budget == 0:
            return 0.0
        return self.session_remaining / self._session_budget
