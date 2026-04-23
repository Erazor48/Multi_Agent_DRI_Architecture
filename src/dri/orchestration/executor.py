"""
Executor — session bootstrap and lifecycle management.

Creates and wires all session-scoped components:
  Session, BudgetManager, AgentRegistry, CommunicationBus, Spawner, RootAgent.

The user-facing CLI only calls Executor.run(pitch) and reads the result.
"""
from __future__ import annotations

from dri.config.settings import settings
from dri.core.budget import BudgetManager
from dri.core.communication import CommunicationBus
from dri.core.memory import ContextBuilder
from dri.core.models import (
    AgentConfig,
    AgentRole,
    AgentState,
    AgentStatus,
    BudgetAllocation,
    Session,
    Task,
)
from dri.core.registry import AgentRegistry
from dri.orchestration.spawner import Spawner
from dri.storage.database import get_session, init_db
from dri.storage.repositories import AgentRepository, SessionRepository


class Executor:
    """
    Wires the full system for one user session and runs it to completion.
    """

    async def run(self, pitch: str, on_status: "Callable[[str], None] | None" = None) -> str:  # type: ignore[name-defined]
        """
        Entry point: receive user pitch, return final CEO report.
        on_status: optional callback called with progress messages.
        """
        from collections.abc import Callable

        await init_db()

        def _notify(msg: str) -> None:
            if on_status:
                on_status(msg)

        _notify("Initializing session...")

        # ── Create session ────────────────────────────────────
        session = Session(
            company_pitch=pitch,
            budget_max_tokens=settings.budget_max_tokens_per_session,
        )
        async with get_session() as db:
            session_repo = SessionRepository(db)
            await session_repo.create(session)
            await session_repo.update_status(session.id, "running")

        # ── Wire session-scoped components ────────────────────
        budget_manager = BudgetManager(settings.budget_max_tokens_per_session)
        registry = AgentRegistry(session_id=session.id, root_agent_id="")  # root_id set below
        bus = CommunicationBus()

        # ── Create root agent config ──────────────────────────
        root_config = AgentConfig(
            role=AgentRole.ROOT,
            title="CEO",
            mission=(
                "You are the CEO of a company being built from a user's pitch. "
                "Design the company structure, spawn your leadership team, "
                "coordinate their work, and deliver a complete executive summary to the user."
            ),
            parent_id=None,
            depth=0,
            model=settings.root_model,
            budget=BudgetAllocation(total=settings.budget_max_tokens_per_session),
        )
        root_state = AgentState(config=root_config, status=AgentStatus.INITIALIZING)

        # ── Persist root agent ────────────────────────────────
        async with get_session() as db:
            agent_repo = AgentRepository(db)
            await agent_repo.create(session.id, root_state)
            session_repo = SessionRepository(db)
            await session_repo.update_root_agent(session.id, root_config.id, "")

        # ── Register root in registry ─────────────────────────
        registry._root_agent_id = root_config.id
        await registry.register(root_state)
        await budget_manager.allocate(root_config.id, settings.budget_max_tokens_per_session)

        # ── Build Spawner ─────────────────────────────────────
        spawner = Spawner(
            session_id=session.id,
            company_name="",         # will be updated by root after design
            company_pitch=pitch,
            registry=registry,
            bus=bus,
            budget_manager=budget_manager,
        )

        # ── Build root context packet ─────────────────────────
        root_context = ContextBuilder.build(
            child_config=root_config,
            parent_title="User",
            company_name="",
            company_pitch=pitch,
        )

        # ── Instantiate RootAgent ─────────────────────────────
        from dri.agents.root import RootAgent

        root_agent = RootAgent(
            context=root_context,
            session_id=session.id,
            registry=registry,
            bus=bus,
            budget_manager=budget_manager,
        )
        root_agent._spawner = spawner  # type: ignore[attr-defined]

        _notify("CEO agent initialized. Designing company structure...")

        # ── Create initial task ───────────────────────────────
        initial_task = Task(
            description=pitch,
            context="",
            assigned_to=root_config.id,
            delegated_by="user",
        )

        # ── Run ───────────────────────────────────────────────
        report = await root_agent.run(initial_task)

        # ── Finalize session ──────────────────────────────────
        async with get_session() as db:
            session_repo = SessionRepository(db)
            await session_repo.add_tokens(session.id, budget_manager.session_used)
            await session_repo.complete(session.id)

        _notify(
            f"Session complete. "
            f"Agents used: {registry.count_total()} | "
            f"Tokens used: {budget_manager.session_used:,}"
        )

        if report.result:
            return report.result
        if report.issues:
            return "[Session failed]\n\n**Error:**\n```\n" + "\n".join(report.issues) + "\n```"
        return "No result produced."
