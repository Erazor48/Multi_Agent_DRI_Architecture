"""
SQLAlchemy ORM models — DB representation of domain models.
Business logic stays in core/models.py — these are pure DB mapping.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SessionORM(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    company_pitch: Mapped[str] = mapped_column(Text)
    company_name: Mapped[str] = mapped_column(String, default="")
    root_agent_id: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="initializing")
    total_tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    budget_max_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    agents: Mapped[list[AgentORM]] = relationship("AgentORM", back_populates="session")
    tasks: Mapped[list[TaskORM]] = relationship("TaskORM", back_populates="session")


class AgentORM(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, ForeignKey("sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    mission: Mapped[str] = mapped_column(Text)
    parent_id: Mapped[str | None] = mapped_column(String, ForeignKey("agents.id"), nullable=True, index=True)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="initializing")
    skills_json: Mapped[str] = mapped_column(Text, default="[]")         # JSON list[Skill]
    allowed_tools_json: Mapped[str] = mapped_column(Text, default="[]")  # JSON list[str]
    budget_total: Mapped[int] = mapped_column(Integer, default=0)
    budget_used: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped[SessionORM] = relationship("SessionORM", back_populates="agents")
    children: Mapped[list["AgentORM"]] = relationship("AgentORM", foreign_keys=[parent_id])
    tasks: Mapped[list["TaskORM"]] = relationship("TaskORM", back_populates="agent", foreign_keys="TaskORM.assigned_to")


class TaskORM(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, ForeignKey("sessions.id"), index=True)
    description: Mapped[str] = mapped_column(Text)
    context: Mapped[str] = mapped_column(Text, default="")
    assigned_to: Mapped[str] = mapped_column(String, ForeignKey("agents.id"), index=True)
    delegated_by: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped[SessionORM] = relationship("SessionORM", back_populates="tasks")
    agent: Mapped[AgentORM] = relationship("AgentORM", back_populates="tasks", foreign_keys=[assigned_to])


class MessageORM(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, ForeignKey("sessions.id"), index=True)
    type: Mapped[str] = mapped_column(String)
    from_agent: Mapped[str] = mapped_column(String, index=True)
    to_agent: Mapped[str] = mapped_column(String, index=True)
    payload_json: Mapped[str] = mapped_column(Text)  # full message JSON
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PersistentCompanyORM(Base):
    __tablename__ = "persistent_companies"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    vision: Mapped[str] = mapped_column(Text)
    pitch: Mapped[str] = mapped_column(Text)
    org_structure_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    messages: Mapped[list["CompanyMessageORM"]] = relationship("CompanyMessageORM", back_populates="company")


class CompanyMessageORM(Base):
    __tablename__ = "company_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    company_id: Mapped[str] = mapped_column(String, ForeignKey("persistent_companies.id"), index=True)
    role: Mapped[str] = mapped_column(String)   # "user" | "ceo"
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    company: Mapped[PersistentCompanyORM] = relationship("PersistentCompanyORM", back_populates="messages")


class ToolCallORM(Base):
    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, ForeignKey("sessions.id"), index=True)
    agent_id: Mapped[str] = mapped_column(String, ForeignKey("agents.id"), index=True)
    task_id: Mapped[str] = mapped_column(String, ForeignKey("tasks.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String)
    input_json: Mapped[str] = mapped_column(Text)
    output_json: Mapped[str] = mapped_column(Text, default="")
    success: Mapped[bool] = mapped_column(default=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    called_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
