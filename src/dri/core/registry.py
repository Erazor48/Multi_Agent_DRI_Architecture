"""
Agent Registry — authoritative in-memory org chart for the running session.
Backed by DB for persistence; in-memory for fast runtime access.
All structural changes (spawn, status update, removal) go through here.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from dri.core.models import AgentRole, AgentState, AgentStatus, OrgChart, OrgNode

if TYPE_CHECKING:
    pass


class AgentRegistry:
    """
    Thread-safe, session-scoped registry of all live agents.

    One registry per session. The Spawner writes to it; agents read from it
    only through the methods defined here — never via direct dict access.
    """

    def __init__(self, session_id: str, root_agent_id: str) -> None:
        self._session_id = session_id
        self._root_agent_id = root_agent_id
        self._nodes: dict[str, OrgNode] = {}
        self._lock = asyncio.Lock()

    # ──────────────────────────────────────────────────────────
    # Write operations (all go through the lock)
    # ──────────────────────────────────────────────────────────

    async def register(self, state: AgentState) -> None:
        cfg = state.config
        node = OrgNode(
            agent_id=cfg.id,
            title=cfg.title,
            role=cfg.role,
            status=state.status,
            depth=cfg.depth,
            parent_id=cfg.parent_id,
        )
        async with self._lock:
            self._nodes[cfg.id] = node
            if cfg.parent_id and cfg.parent_id in self._nodes:
                self._nodes[cfg.parent_id].children_ids.append(cfg.id)

    async def update_status(self, agent_id: str, status: AgentStatus) -> None:
        async with self._lock:
            if agent_id in self._nodes:
                self._nodes[agent_id].status = status

    async def add_tokens(self, agent_id: str, tokens: int) -> None:
        async with self._lock:
            if agent_id in self._nodes:
                self._nodes[agent_id].tokens_used += tokens

    async def remove(self, agent_id: str) -> None:
        """Remove an agent (e.g. after it completes and is archived)."""
        async with self._lock:
            node = self._nodes.pop(agent_id, None)
            if node and node.parent_id and node.parent_id in self._nodes:
                parent = self._nodes[node.parent_id]
                parent.children_ids = [c for c in parent.children_ids if c != agent_id]

    # ──────────────────────────────────────────────────────────
    # Read operations (lock-free snapshots — Python GIL safe for reads)
    # ──────────────────────────────────────────────────────────

    def get_node(self, agent_id: str) -> OrgNode | None:
        return self._nodes.get(agent_id)

    def get_children(self, parent_id: str) -> list[OrgNode]:
        node = self._nodes.get(parent_id)
        if node is None:
            return []
        return [self._nodes[cid] for cid in node.children_ids if cid in self._nodes]

    def get_parent(self, agent_id: str) -> OrgNode | None:
        node = self._nodes.get(agent_id)
        if node is None or node.parent_id is None:
            return None
        return self._nodes.get(node.parent_id)

    def count_active(self) -> int:
        return sum(1 for n in self._nodes.values() if n.status == AgentStatus.ACTIVE)

    def count_total(self) -> int:
        return len(self._nodes)

    def depth_of(self, agent_id: str) -> int:
        node = self._nodes.get(agent_id)
        return node.depth if node else -1

    def agents_at_depth(self, depth: int) -> list[OrgNode]:
        return [n for n in self._nodes.values() if n.depth == depth]

    def all_workers(self) -> list[OrgNode]:
        return [n for n in self._nodes.values() if n.role == AgentRole.WORKER]

    def all_managers(self) -> list[OrgNode]:
        return [n for n in self._nodes.values() if n.role == AgentRole.MANAGER]

    def all_done(self) -> bool:
        non_root = [n for n in self._nodes.values() if n.role != AgentRole.ROOT]
        if not non_root:
            return False
        return all(n.status in (AgentStatus.DONE, AgentStatus.FAILED) for n in non_root)

    def snapshot(self) -> OrgChart:
        """Return an immutable snapshot of the current org chart."""
        return OrgChart(
            session_id=self._session_id,
            root_id=self._root_agent_id,
            nodes=dict(self._nodes),
        )
