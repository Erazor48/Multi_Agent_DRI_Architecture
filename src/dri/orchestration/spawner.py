"""
Spawner — the single mechanism by which a parent creates a child agent.

Flow:
1. Parent builds a SpawnRequest
2. Spawner validates depth/concurrency limits
3. Spawner builds AgentConfig + AgentState from the request
4. Spawner builds ContextPacket (memory injection)
5. Spawner instantiates the correct agent class
6. Spawner persists the agent to DB and registers it in the registry
7. Spawner allocates budget
8. Returns the live agent instance (caller starts it)
"""
from __future__ import annotations

import re
import unicodedata
from typing import Callable

from dri.config.settings import settings
from dri.core.budget import BudgetManager
from dri.core.communication import CommunicationBus
from dri.core.memory import ContextBuilder, ContextPacket
from dri.core.models import (
    AgentConfig,
    AgentRole,
    AgentState,
    AgentStatus,
    BudgetAllocation,
    SpawnRequest,
    WorkspacePermission,
)
from dri.core.registry import AgentRegistry
from dri.storage.database import get_session
from dri.storage.repositories import AgentRepository


class SpawnLimitError(Exception):
    """Raised when a spawn request would violate system limits."""


class Spawner:
    """
    Stateless factory — call spawn() to create a new agent.
    One Spawner instance is shared for the entire session.
    """

    def __init__(
        self,
        session_id: str,
        company_name: str,
        company_pitch: str,
        registry: AgentRegistry,
        bus: CommunicationBus,
        budget_manager: BudgetManager,
        workspace_root: str = "",
        root_workspace_access: bool = False,
        on_progress: Callable[[str], None] | None = None,
        budget_overrides: dict[str, int] | None = None,
        company_kb: str = "",
        company_history_snippet: str = "",
    ) -> None:
        self._session_id = session_id
        self._company_name = company_name
        self._company_pitch = company_pitch
        self._registry = registry
        self._bus = bus
        self._budget_manager = budget_manager
        self._workspace_root = workspace_root
        # When True, all spawned agents get full workspace access (used by task forces).
        self._root_workspace_access = root_workspace_access
        # Progress callback: called by any agent in the tree on each tool execution.
        self._on_progress: Callable[[str], None] = on_progress or (lambda _: None)
        # Custom token budgets set via `dri company team promote` (Layer 5, Gap 3).
        self._budget_overrides: dict[str, int] = budget_overrides or {}
        # Company-level context injected into every spawned agent's system prompt.
        self._company_kb: str = company_kb
        self._company_history_snippet: str = company_history_snippet

    def report_progress(self, message: str) -> None:
        """Called by agents to surface tool-call activity to the outer status observer."""
        self._on_progress(message)

    @staticmethod
    def _slug(name: str) -> str:
        # Decompose accented chars (é→e, ç→c, etc.) before slugifying
        normalized = unicodedata.normalize("NFD", name.lower())
        ascii_only = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
        return re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")

    def _workspace_permissions(
        self, role: AgentRole, title: str, parent_title: str
    ) -> list[WorkspacePermission]:
        """Return the workspace permission list for an agent based on its role."""
        if not self._workspace_root:
            return []
        # ROOT role or task-force context: full workspace access
        if role == AgentRole.ROOT or self._root_workspace_access:
            return [WorkspacePermission(path="", can_read=True, can_write=True, can_delete=True)]
        if role == AgentRole.MANAGER:
            dept = self._slug(title)
            return [
                WorkspacePermission(path=f"{dept}/", can_read=True, can_write=True, can_delete=True),
                WorkspacePermission(path="shared/", can_read=True, can_write=True, can_delete=True),
                WorkspacePermission(path="", can_read=True, can_write=False, can_delete=False),
            ]
        # WORKER — dept derived from parent manager's title
        dept = self._slug(parent_title)
        return [
            WorkspacePermission(path=f"{dept}/", can_read=True, can_write=True, can_delete=True),
            WorkspacePermission(path="shared/", can_read=True, can_write=True, can_delete=True),
            WorkspacePermission(path="", can_read=True, can_write=False, can_delete=False),
        ]

    async def spawn(
        self,
        request: SpawnRequest,
        prior_results: list[str] | None = None,
        constraints: list[str] | None = None,
        parent_title: str = "Manager",
    ) -> "BaseAgent":  # type: ignore[name-defined]  # forward ref resolved at runtime
        from dri.agents.base import BaseAgent
        from dri.agents.manager import ManagerAgent
        from dri.agents.worker import WorkerAgent

        # ── Validate limits ───────────────────────────────────
        child_depth = request.parent_depth + 1
        if child_depth > settings.max_spawn_depth:
            raise SpawnLimitError(
                f"Max spawn depth ({settings.max_spawn_depth}) reached. "
                f"Cannot spawn '{request.title}' at depth {child_depth}."
            )

        if self._registry.count_active() >= settings.max_concurrent_agents:
            raise SpawnLimitError(
                f"Max concurrent agents ({settings.max_concurrent_agents}) reached."
            )

        # ── Build domain model ────────────────────────────────
        model = request.model or (
            settings.root_model if request.role == AgentRole.ROOT else settings.default_model
        )
        import uuid as _uuid
        metadata = dict(request.metadata)
        metadata["depth"] = child_depth  # inject depth so child managers know their own depth

        # Apply custom token budget from Layer 5 if the founder set one via `team promote`.
        effective_budget = self._budget_overrides.get(request.title) or request.budget_tokens

        config = AgentConfig(
            id=metadata.pop("agent_id", None) or str(_uuid.uuid4()),
            role=request.role,
            title=request.title,
            mission=request.mission,
            parent_id=request.parent_id,
            depth=child_depth,
            model=model,
            skills=list(request.skills),
            allowed_tools=list(request.allowed_tools),
            budget=BudgetAllocation(total=effective_budget),
            metadata=metadata,
        )
        state = AgentState(config=config, status=AgentStatus.INITIALIZING)

        # ── Persist to DB ─────────────────────────────────────
        async with get_session() as db:
            agent_repo = AgentRepository(db)
            await agent_repo.create(self._session_id, state)

        # ── Register in registry ──────────────────────────────
        await self._registry.register(state)

        # ── Allocate budget ───────────────────────────────────
        await self._budget_manager.allocate(config.id, effective_budget)

        # ── Auto-include file tools for all workspace agents ─────
        # All workspace agents get the full file toolkit automatically.
        # RBAC (workspace_permissions) enforces what they can actually access.
        # The parent LLM decides WHAT to do, not whether the tools exist.
        if self._workspace_root:
            for _t in ("file_list", "file_read", "file_write", "file_delete"):
                if _t not in config.allowed_tools:
                    config.allowed_tools.append(_t)

        # ── Build context packet ──────────────────────────────
        config.metadata["parent_id"] = request.parent_id or ""
        ws_perms = self._workspace_permissions(request.role, request.title, parent_title)
        # memory_dept: the dept folder under which _knowledge/<slug>/ lives.
        # Managers own their own dept; workers share their parent manager's dept.
        # This must be explicit because task-force agents receive path="" perms
        # which AgentMemory.for_agent() cannot use to derive the dept.
        if request.role in (AgentRole.MANAGER, AgentRole.ROOT):
            memory_dept = self._slug(request.title)
        else:
            memory_dept = self._slug(parent_title)
        context = ContextBuilder.build(
            child_config=config,
            parent_title=parent_title,
            company_name=self._company_name,
            company_pitch=self._company_pitch,
            prior_results=prior_results,
            constraints=constraints,
            workspace_root=self._workspace_root,
            workspace_permissions=ws_perms,
            memory_dept=memory_dept,
            company_kb=self._company_kb,
            company_history_snippet=self._company_history_snippet,
        )

        # ── Instantiate correct class ─────────────────────────
        agent_class: type[BaseAgent]
        if request.role == AgentRole.WORKER:
            agent_class = WorkerAgent
        else:
            agent_class = ManagerAgent

        agent = agent_class(
            context=context,
            session_id=self._session_id,
            registry=self._registry,
            bus=self._bus,
            budget_manager=self._budget_manager,
        )

        # Attach spawner reference so managers can spawn their own children
        if isinstance(agent, ManagerAgent):
            agent._spawner = self  # type: ignore[attr-defined]

        # Propagate progress callback to every agent (workers + managers)
        agent._spawner_ref = self  # type: ignore[attr-defined]

        return agent
