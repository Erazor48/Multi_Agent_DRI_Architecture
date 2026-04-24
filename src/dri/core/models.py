"""
All domain models for the DRI system.
These are pure Pydantic models — no DB or LLM logic here.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────
# Enumerations
# ──────────────────────────────────────────────────────────────


class AgentRole(str, Enum):
    ROOT = "root"
    MANAGER = "manager"
    WORKER = "worker"


class AgentStatus(str, Enum):
    INITIALIZING = "initializing"
    ACTIVE = "active"
    WAITING = "waiting"   # spawned children, aggregating results
    DONE = "done"
    FAILED = "failed"


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


class MessageType(str, Enum):
    DELEGATE = "delegate"   # parent → child
    REPORT = "report"       # child → parent
    ESCALATE = "escalate"   # child → parent (unplanned: blocker / budget)


# ──────────────────────────────────────────────────────────────
# Skills
# ──────────────────────────────────────────────────────────────


class Skill(BaseModel):
    """A natural-language capability descriptor injected into an agent's system prompt."""

    name: str
    description: str
    instructions: str
    required_tools: list[str] = Field(default_factory=list)

    def to_prompt_block(self) -> str:
        return (
            f"### Skill: {self.name}\n"
            f"{self.description}\n\n"
            f"{self.instructions}"
        )


# ──────────────────────────────────────────────────────────────
# Budget
# ──────────────────────────────────────────────────────────────


class BudgetAllocation(BaseModel):
    """Token budget for one agent."""

    total: int = Field(..., ge=0)
    used: int = Field(0, ge=0)

    @property
    def remaining(self) -> int:
        return max(0, self.total - self.used)

    @property
    def fraction_remaining(self) -> float:
        if self.total == 0:
            return 0.0
        return self.remaining / self.total

    def deduct(self, tokens: int) -> None:
        self.used = min(self.total, self.used + tokens)

    def is_depleted(self) -> bool:
        return self.remaining == 0


# ──────────────────────────────────────────────────────────────
# Agent
# ──────────────────────────────────────────────────────────────


class AgentConfig(BaseModel):
    """Immutable configuration passed to an agent at creation time."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: AgentRole
    title: str                          # e.g. "Chief Marketing Officer"
    mission: str                        # one paragraph describing what this agent must accomplish
    parent_id: str | None = None
    depth: int = Field(0, ge=0)         # 0 = root
    model: str = ""                     # empty = use settings.default_model
    skills: list[Skill] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    budget: BudgetAllocation = Field(default_factory=lambda: BudgetAllocation(total=0))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentState(BaseModel):
    """Mutable runtime state for a live agent."""

    config: AgentConfig
    status: AgentStatus = AgentStatus.INITIALIZING
    children_ids: list[str] = Field(default_factory=list)
    current_task_id: str | None = None
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: str | None = None

    def touch(self) -> None:
        self.last_updated = datetime.now(timezone.utc)


# ──────────────────────────────────────────────────────────────
# Tasks
# ──────────────────────────────────────────────────────────────


class Task(BaseModel):
    """A unit of work delegated to an agent."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    context: str = ""                   # relevant background, injected by parent
    assigned_to: str                    # agent id
    delegated_by: str                   # agent id (parent)
    status: TaskStatus = TaskStatus.PENDING
    result: str | None = None
    error: str | None = None
    tokens_used: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    def complete(self, result: str, tokens_used: int) -> None:
        self.result = result
        self.tokens_used = tokens_used
        self.status = TaskStatus.DONE
        self.completed_at = datetime.now(timezone.utc)

    def fail(self, error: str) -> None:
        self.error = error
        self.status = TaskStatus.FAILED
        self.completed_at = datetime.now(timezone.utc)


# ──────────────────────────────────────────────────────────────
# Messages (inter-agent communication)
# ──────────────────────────────────────────────────────────────


class Message(BaseModel):
    """Base envelope for all inter-agent messages."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: MessageType
    from_agent: str
    to_agent: str
    sent_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DelegateMessage(Message):
    """Parent → child: here is your task."""

    type: MessageType = MessageType.DELEGATE
    task: Task


class ReportMessage(Message):
    """Child → parent: here is my result."""

    type: MessageType = MessageType.REPORT
    task_id: str
    result: str
    status: TaskStatus
    tokens_used: int
    child_agent_id: str
    issues: list[str] = Field(default_factory=list)


class EscalateMessage(Message):
    """Child → parent: I have a blocker I cannot resolve alone."""

    type: MessageType = MessageType.ESCALATE
    task_id: str
    reason: str                         # "budget_low" | "blocker" | "ambiguous_mission"
    detail: str


# ──────────────────────────────────────────────────────────────
# Spawn
# ──────────────────────────────────────────────────────────────


class SpawnRequest(BaseModel):
    """What a parent sends to the Spawner to create a child agent."""

    parent_id: str
    parent_depth: int
    role: AgentRole
    title: str
    mission: str
    skills: list[Skill] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    budget_tokens: int
    model: str = ""
    initial_task: Task | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────
# Org chart
# ──────────────────────────────────────────────────────────────


class OrgNode(BaseModel):
    """One node in the org chart tree (in-memory view)."""

    agent_id: str
    title: str
    role: AgentRole
    status: AgentStatus
    depth: int
    parent_id: str | None
    children_ids: list[str] = Field(default_factory=list)
    tokens_used: int = 0

    def is_leaf(self) -> bool:
        return len(self.children_ids) == 0


class OrgChart(BaseModel):
    """Full org chart snapshot."""

    session_id: str
    root_id: str
    nodes: dict[str, OrgNode] = Field(default_factory=dict)

    def get_node(self, agent_id: str) -> OrgNode | None:
        return self.nodes.get(agent_id)

    def get_children(self, agent_id: str) -> list[OrgNode]:
        node = self.get_node(agent_id)
        if node is None:
            return []
        return [self.nodes[cid] for cid in node.children_ids if cid in self.nodes]

    def all_done(self) -> bool:
        return all(n.status in (AgentStatus.DONE, AgentStatus.FAILED) for n in self.nodes.values())


# ──────────────────────────────────────────────────────────────
# Workspace permissions
# ──────────────────────────────────────────────────────────────


class WorkspacePermission(BaseModel):
    """Access rule for one path inside an agent's company workspace."""

    path: str = ""          # relative to company workspace root; "" = entire root
    can_read: bool = True
    can_write: bool = False
    can_delete: bool = False


# ──────────────────────────────────────────────────────────────
# Persistent Company
# ──────────────────────────────────────────────────────────────


class PersistentCompany(BaseModel):
    """A company that persists across sessions — has memory, identity, and ongoing strategy."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    vision: str
    pitch: str
    org_structure: list[dict[str, Any]] = Field(default_factory=list)  # departments array
    status: str = "active"  # active | archived
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CompanyMessage(BaseModel):
    """One turn in the ongoing conversation with a persistent company CEO."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    company_id: str
    role: str  # "user" | "ceo"
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ──────────────────────────────────────────────────────────────
# Session
# ──────────────────────────────────────────────────────────────


class Session(BaseModel):
    """A single user ↔ system interaction session."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    company_pitch: str
    company_name: str = ""
    root_agent_id: str = ""
    status: str = "initializing"        # initializing | running | done | failed
    total_tokens_used: int = 0
    budget_max_tokens: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
