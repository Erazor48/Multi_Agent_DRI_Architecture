"""
Repository layer — all DB access goes through these classes.
No business logic here; only mapping between domain models and ORM.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dri.core.models import (
    AgentConfig,
    AgentRole,
    AgentState,
    AgentStatus,
    BudgetAllocation,
    CompanyMessage,
    Message,
    PersistentCompany,
    Session,
    Skill,
    Task,
    TaskStatus,
)
from dri.storage.orm import AgentORM, CompanyMessageORM, MessageORM, PersistentCompanyORM, SessionORM, TaskORM, ToolCallORM


# ──────────────────────────────────────────────────────────────
# Session Repository
# ──────────────────────────────────────────────────────────────


class SessionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(self, session: Session) -> None:
        orm = SessionORM(
            id=session.id,
            company_pitch=session.company_pitch,
            company_name=session.company_name,
            root_agent_id=session.root_agent_id,
            status=session.status,
            total_tokens_used=session.total_tokens_used,
            budget_max_tokens=session.budget_max_tokens,
            created_at=session.created_at,
        )
        self._db.add(orm)

    async def get(self, session_id: str) -> Session | None:
        result = await self._db.get(SessionORM, session_id)
        if result is None:
            return None
        return self._orm_to_domain(result)

    async def update_status(self, session_id: str, status: str) -> None:
        await self._db.execute(
            update(SessionORM).where(SessionORM.id == session_id).values(status=status)
        )

    async def update_root_agent(self, session_id: str, root_agent_id: str, company_name: str) -> None:
        await self._db.execute(
            update(SessionORM)
            .where(SessionORM.id == session_id)
            .values(root_agent_id=root_agent_id, company_name=company_name)
        )

    async def add_tokens(self, session_id: str, tokens: int) -> None:
        result = await self._db.get(SessionORM, session_id)
        if result:
            result.total_tokens_used += tokens

    async def complete(self, session_id: str) -> None:
        await self._db.execute(
            update(SessionORM)
            .where(SessionORM.id == session_id)
            .values(status="done", completed_at=datetime.now(timezone.utc))
        )

    @staticmethod
    def _orm_to_domain(orm: SessionORM) -> Session:
        return Session(
            id=orm.id,
            company_pitch=orm.company_pitch,
            company_name=orm.company_name,
            root_agent_id=orm.root_agent_id,
            status=orm.status,
            total_tokens_used=orm.total_tokens_used,
            budget_max_tokens=orm.budget_max_tokens,
            created_at=orm.created_at,
            completed_at=orm.completed_at,
        )


# ──────────────────────────────────────────────────────────────
# Agent Repository
# ──────────────────────────────────────────────────────────────


class AgentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(self, session_id: str, state: AgentState) -> None:
        cfg = state.config
        orm = AgentORM(
            id=cfg.id,
            session_id=session_id,
            role=cfg.role.value,
            title=cfg.title,
            mission=cfg.mission,
            parent_id=cfg.parent_id,
            depth=cfg.depth,
            model=cfg.model,
            status=state.status.value,
            skills_json=json.dumps([s.model_dump() for s in cfg.skills]),
            allowed_tools_json=json.dumps(cfg.allowed_tools),
            budget_total=cfg.budget.total,
            budget_used=cfg.budget.used,
            metadata_json=json.dumps(cfg.metadata),
            created_at=cfg.created_at,
            last_updated=state.last_updated,
        )
        self._db.add(orm)

    async def get(self, agent_id: str) -> AgentState | None:
        result = await self._db.get(AgentORM, agent_id)
        if result is None:
            return None
        return self._orm_to_domain(result)

    async def list_by_session(self, session_id: str) -> list[AgentState]:
        result = await self._db.execute(
            select(AgentORM).where(AgentORM.session_id == session_id)
        )
        return [self._orm_to_domain(row) for row in result.scalars()]

    async def list_children(self, parent_id: str) -> list[AgentState]:
        result = await self._db.execute(
            select(AgentORM).where(AgentORM.parent_id == parent_id)
        )
        return [self._orm_to_domain(row) for row in result.scalars()]

    async def update_status(self, agent_id: str, status: AgentStatus, error: str | None = None) -> None:
        values: dict = {"status": status.value, "last_updated": datetime.now(timezone.utc)}
        if error is not None:
            values["error"] = error
        await self._db.execute(
            update(AgentORM).where(AgentORM.id == agent_id).values(**values)
        )

    async def deduct_budget(self, agent_id: str, tokens: int) -> None:
        result = await self._db.get(AgentORM, agent_id)
        if result:
            result.budget_used = min(result.budget_total, result.budget_used + tokens)
            result.last_updated = datetime.now(timezone.utc)

    async def get_budget(self, agent_id: str) -> BudgetAllocation | None:
        result = await self._db.get(AgentORM, agent_id)
        if result is None:
            return None
        return BudgetAllocation(total=result.budget_total, used=result.budget_used)

    @staticmethod
    def _orm_to_domain(orm: AgentORM) -> AgentState:
        skills = [Skill(**s) for s in json.loads(orm.skills_json)]
        cfg = AgentConfig(
            id=orm.id,
            role=AgentRole(orm.role),
            title=orm.title,
            mission=orm.mission,
            parent_id=orm.parent_id,
            depth=orm.depth,
            model=orm.model,
            skills=skills,
            allowed_tools=json.loads(orm.allowed_tools_json),
            budget=BudgetAllocation(total=orm.budget_total, used=orm.budget_used),
            created_at=orm.created_at,
            metadata=json.loads(orm.metadata_json),
        )
        return AgentState(
            config=cfg,
            status=AgentStatus(orm.status),
            last_updated=orm.last_updated,
            error=orm.error,
        )


# ──────────────────────────────────────────────────────────────
# Task Repository
# ──────────────────────────────────────────────────────────────


class TaskRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(self, session_id: str, task: Task) -> None:
        orm = TaskORM(
            id=task.id,
            session_id=session_id,
            description=task.description,
            context=task.context,
            assigned_to=task.assigned_to,
            delegated_by=task.delegated_by,
            status=task.status.value,
            created_at=task.created_at,
        )
        self._db.add(orm)

    async def get(self, task_id: str) -> Task | None:
        result = await self._db.get(TaskORM, task_id)
        if result is None:
            return None
        return self._orm_to_domain(result)

    async def list_by_agent(self, agent_id: str) -> list[Task]:
        result = await self._db.execute(
            select(TaskORM).where(TaskORM.assigned_to == agent_id)
        )
        return [self._orm_to_domain(row) for row in result.scalars()]

    async def complete(self, task_id: str, result: str, tokens_used: int) -> None:
        await self._db.execute(
            update(TaskORM)
            .where(TaskORM.id == task_id)
            .values(
                status=TaskStatus.DONE.value,
                result=result,
                tokens_used=tokens_used,
                completed_at=datetime.now(timezone.utc),
            )
        )

    async def fail(self, task_id: str, error: str) -> None:
        await self._db.execute(
            update(TaskORM)
            .where(TaskORM.id == task_id)
            .values(
                status=TaskStatus.FAILED.value,
                error=error,
                completed_at=datetime.now(timezone.utc),
            )
        )

    async def set_in_progress(self, task_id: str) -> None:
        await self._db.execute(
            update(TaskORM)
            .where(TaskORM.id == task_id)
            .values(status=TaskStatus.IN_PROGRESS.value)
        )

    @staticmethod
    def _orm_to_domain(orm: TaskORM) -> Task:
        return Task(
            id=orm.id,
            description=orm.description,
            context=orm.context,
            assigned_to=orm.assigned_to,
            delegated_by=orm.delegated_by,
            status=TaskStatus(orm.status),
            result=orm.result,
            error=orm.error,
            tokens_used=orm.tokens_used,
            created_at=orm.created_at,
            completed_at=orm.completed_at,
        )


# ──────────────────────────────────────────────────────────────
# Message Repository
# ──────────────────────────────────────────────────────────────


class MessageRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def log(self, session_id: str, message: Message, payload: dict) -> None:
        orm = MessageORM(
            id=message.id,
            session_id=session_id,
            type=message.type.value,
            from_agent=message.from_agent,
            to_agent=message.to_agent,
            payload_json=json.dumps(payload),
            sent_at=message.sent_at,
        )
        self._db.add(orm)


# ──────────────────────────────────────────────────────────────
# Persistent Company Repository
# ──────────────────────────────────────────────────────────────


class PersistentCompanyRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(self, company: PersistentCompany) -> None:
        import json
        orm = PersistentCompanyORM(
            id=company.id,
            name=company.name,
            vision=company.vision,
            pitch=company.pitch,
            org_structure_json=json.dumps(company.org_structure),
            status=company.status,
            created_at=company.created_at,
        )
        self._db.add(orm)

    async def get(self, company_id: str) -> PersistentCompany | None:
        import json
        result = await self._db.get(PersistentCompanyORM, company_id)
        if result is None:
            return None
        return PersistentCompany(
            id=result.id,
            name=result.name,
            vision=result.vision,
            pitch=result.pitch,
            org_structure=json.loads(result.org_structure_json),
            status=result.status,
            created_at=result.created_at,
        )

    async def get_latest(self) -> PersistentCompany | None:
        import json
        result = await self._db.execute(
            select(PersistentCompanyORM)
            .where(PersistentCompanyORM.status == "active")
            .order_by(PersistentCompanyORM.created_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return PersistentCompany(
            id=row.id,
            name=row.name,
            vision=row.vision,
            pitch=row.pitch,
            org_structure=json.loads(row.org_structure_json),
            status=row.status,
            created_at=row.created_at,
        )

    async def remove_department(self, company_id: str, dept_title: str) -> bool:
        """Remove a department from org_structure. Returns True if found and removed."""
        import json
        result = await self._db.get(PersistentCompanyORM, company_id)
        if result is None:
            return False
        org = json.loads(result.org_structure_json)
        new_org = [d for d in org if d.get("title", "").lower() != dept_title.lower()]
        if len(new_org) == len(org):
            return False
        result.org_structure_json = json.dumps(new_org)
        return True

    async def list_active(self) -> list[PersistentCompany]:
        import json
        result = await self._db.execute(
            select(PersistentCompanyORM)
            .where(PersistentCompanyORM.status == "active")
            .order_by(PersistentCompanyORM.created_at.desc())
        )
        return [
            PersistentCompany(
                id=row.id, name=row.name, vision=row.vision, pitch=row.pitch,
                org_structure=json.loads(row.org_structure_json),
                status=row.status, created_at=row.created_at,
            )
            for row in result.scalars()
        ]


class CompanyMessageRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def add(self, msg: CompanyMessage) -> None:
        orm = CompanyMessageORM(
            id=msg.id,
            company_id=msg.company_id,
            role=msg.role,
            content=msg.content,
            created_at=msg.created_at,
        )
        self._db.add(orm)

    async def list_by_company(self, company_id: str) -> list[CompanyMessage]:
        result = await self._db.execute(
            select(CompanyMessageORM)
            .where(CompanyMessageORM.company_id == company_id)
            .order_by(CompanyMessageORM.created_at.asc())
        )
        return [
            CompanyMessage(
                id=row.id, company_id=row.company_id,
                role=row.role, content=row.content, created_at=row.created_at,
            )
            for row in result.scalars()
        ]


# ──────────────────────────────────────────────────────────────
# Tool Call Repository
# ──────────────────────────────────────────────────────────────


class ToolCallRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def log(
        self,
        *,
        call_id: str,
        session_id: str,
        agent_id: str,
        task_id: str,
        tool_name: str,
        input_data: dict,
        output_data: dict,
        success: bool,
        duration_ms: int,
    ) -> None:
        orm = ToolCallORM(
            id=call_id,
            session_id=session_id,
            agent_id=agent_id,
            task_id=task_id,
            tool_name=tool_name,
            input_json=json.dumps(input_data),
            output_json=json.dumps(output_data),
            success=success,
            duration_ms=duration_ms,
        )
        self._db.add(orm)
