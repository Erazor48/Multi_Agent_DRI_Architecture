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
    ) -> None:
        self._session_id = session_id
        self._company_name = company_name
        self._company_pitch = company_pitch
        self._registry = registry
        self._bus = bus
        self._budget_manager = budget_manager

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
            budget=BudgetAllocation(total=request.budget_tokens),
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
        await self._budget_manager.allocate(config.id, request.budget_tokens)

        # ── Build context packet ──────────────────────────────
        config.metadata["parent_id"] = request.parent_id or ""
        context = ContextBuilder.build(
            child_config=config,
            parent_title=parent_title,
            company_name=self._company_name,
            company_pitch=self._company_pitch,
            prior_results=prior_results,
            constraints=constraints,
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

        return agent
