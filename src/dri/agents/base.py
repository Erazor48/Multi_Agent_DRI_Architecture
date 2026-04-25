"""
BaseAgent — shared logic for all agent types.

Handles:
- LLM calls (via provider abstraction, budget enforcement)
- Tool dispatch (agentic loop: call → tool_use → result → repeat)
- Status lifecycle management
- Message handling (subscribe to bus, dispatch incoming messages)
- DB persistence (via repositories)

Concrete agents (RootAgent, ManagerAgent, WorkerAgent) override
`_run_task()` to implement their specific behavior.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dri.config.settings import settings
from dri.core.budget import BudgetExceededError, BudgetManager, BudgetWarning
from dri.core.communication import CommunicationBus
from dri.core.memory import ContextPacket
from dri.core.models import (
    AgentStatus,
    EscalateMessage,
    Message,
    MessageType,
    ReportMessage,
    Task,
    TaskStatus,
)
from dri.core.registry import AgentRegistry
from dri.llm.base import BaseLLMProvider, LLMResponse
from dri.llm.factory import create_provider
from dri.storage.database import get_session
from dri.storage.repositories import AgentRepository, MessageRepository, TaskRepository, ToolCallRepository
from dri.tools.base import ToolRegistry
import dri.tools  # noqa: F401 — trigger all tool registrations

if TYPE_CHECKING:
    pass


class BaseAgent(ABC):
    """
    Abstract base for all DRI agents.

    Constructor receives the assembled ContextPacket (from the parent via Spawner).
    The agent never constructs its own context — isolation is enforced by design.
    """

    def __init__(
        self,
        context: ContextPacket,
        session_id: str,
        registry: AgentRegistry,
        bus: CommunicationBus,
        budget_manager: BudgetManager,
        provider: BaseLLMProvider | None = None,
    ) -> None:
        self._ctx = context
        self._session_id = session_id
        self._registry = registry
        self._bus = bus
        self._budget_manager = budget_manager
        # Provider injected externally (for tests) or created from settings
        self._provider: BaseLLMProvider = provider or create_provider()
        self._model = context.model or settings.default_model
        self._pending_reports: asyncio.Queue[ReportMessage] = asyncio.Queue()
        self._pending_escalations: asyncio.Queue[EscalateMessage] = asyncio.Queue()

        self._bus.subscribe(self._ctx.agent_id, self._on_message)

    # ──────────────────────────────────────────────────────────
    # Public interface
    # ──────────────────────────────────────────────────────────

    @property
    def agent_id(self) -> str:
        return self._ctx.agent_id

    async def run(self, task: Task) -> ReportMessage:
        """
        Execute the assigned task. Returns a ReportMessage with the result.
        This is the only entry point for running an agent.
        """
        await self._set_status(AgentStatus.ACTIVE)

        async with get_session() as db:
            task_repo = TaskRepository(db)
            await task_repo.set_in_progress(task.id)

        try:
            result = await asyncio.wait_for(
                self._run_task(task),
                timeout=settings.agent_timeout_seconds,
            )
            self._cleanup_wip()
            await self._set_status(AgentStatus.DONE)
            alloc = self._budget_manager.get_allocation(self.agent_id)
            report = ReportMessage(
                from_agent=self.agent_id,
                to_agent=task.delegated_by,
                task_id=task.id,
                result=result,
                status=TaskStatus.DONE,
                tokens_used=alloc.used if alloc else 0,
                child_agent_id=self.agent_id,
            )
            await self._persist_task_done(task.id, result)
            return report

        except asyncio.TimeoutError:
            error = f"Agent {self._ctx.title} timed out after {settings.agent_timeout_seconds}s."
            await self._set_status(AgentStatus.FAILED, error=error)
            await self._persist_task_failed(task.id, error)
            self._cleanup_wip()  # remove WIP first so inventory only shows deliverables
            return self._fail_report(task, error)

        except BudgetExceededError as e:
            error = str(e)
            await self._set_status(AgentStatus.FAILED, error=error)
            await self._persist_task_failed(task.id, error)
            self._cleanup_wip()
            return self._fail_report(task, error)

        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            await self._set_status(AgentStatus.FAILED, error=error)
            await self._persist_task_failed(task.id, error)
            self._cleanup_wip()
            return self._fail_report(task, error)

        finally:
            self._bus.unsubscribe(self.agent_id)

    # ──────────────────────────────────────────────────────────
    # Abstract — subclasses implement this
    # ──────────────────────────────────────────────────────────

    @abstractmethod
    async def _run_task(self, task: Task) -> str:
        """
        Execute the agent's specific behavior for a task.
        Return the result as a string to be reported to the parent.
        """

    # ──────────────────────────────────────────────────────────
    # LLM interaction
    # ──────────────────────────────────────────────────────────

    async def _call_llm(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        estimated_tokens: int = 4000,
    ) -> LLMResponse:
        """
        Make a single LLM call with budget enforcement.
        All LLM calls in the system go through this method — no exceptions.
        Retry logic is handled by each provider.
        """
        try:
            await self._budget_manager.check_and_deduct(self.agent_id, estimated_tokens)
        except BudgetWarning as w:
            await self._escalate_budget_warning(w.fraction_remaining)
            # Non-blocking — continue after escalating

        response = await self._provider.call(
            system=self._ctx.to_system_prompt(),
            messages=messages,
            tools=tools,
            model=self._model,
            max_tokens=settings.max_tokens_per_response,
        )

        actual_tokens = response.input_tokens + response.output_tokens
        await self._budget_manager.record_actual(self.agent_id, estimated_tokens, actual_tokens)
        await self._registry.add_tokens(self.agent_id, actual_tokens)

        async with get_session() as db:
            agent_repo = AgentRepository(db)
            await agent_repo.deduct_budget(self.agent_id, actual_tokens)

        return response

    async def _agentic_loop(
        self,
        initial_messages: list[dict[str, Any]],
        task_id: str,
    ) -> str:
        """
        Run the full tool-use agentic loop until the model produces a final text response.
        Returns the final text content.
        """
        tool_specs = ToolRegistry.to_claude_specs(self._ctx.allowed_tools)
        messages = list(initial_messages)
        final_text = ""

        for _ in range(20):  # max 20 tool call rounds
            response = await self._call_llm(messages, tools=tool_specs or None)
            final_text = response.text

            # Add assistant turn to history
            messages.append(response.to_assistant_message())

            if not response.has_tool_calls:
                return final_text

            # Execute all tool calls in parallel and collect results
            tool_results = await asyncio.gather(
                *[self._execute_tool(tc, task_id) for tc in response.tool_calls]
            )

            # Add tool results as next user turn
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_call_id": r["tool_call_id"],
                        "content": r["content"],
                    }
                    for r in tool_results
                ],
            })

        return final_text or "Maximum tool call rounds reached."

    _FILE_TOOLS = {"file_read", "file_write", "file_list", "file_delete"}
    _EXTERNAL_TOOLS = {"propose_external_action"}

    async def _execute_tool(self, tool_call: Any, task_id: str) -> dict[str, Any]:
        """Execute one tool call, log it, and return a result dict."""
        call_id = str(uuid.uuid4())
        tool_name = tool_call.name
        tool_input = dict(tool_call.input or {})
        start = time.time()

        # Inject workspace context into file tools
        if tool_name in self._FILE_TOOLS and self._ctx.workspace_root:
            tool_input["_workspace_root"] = self._ctx.workspace_root
            tool_input["_permissions"] = [
                p.model_dump() for p in self._ctx.workspace_permissions
            ]

        # Inject agent identity into external action tools
        if tool_name in self._EXTERNAL_TOOLS:
            tool_input["_workspace_root"] = self._ctx.workspace_root
            tool_input["_agent_title"] = self._ctx.title
            tool_input["_company_name"] = self._ctx.company_name

        try:
            tool = ToolRegistry.get(tool_name)
            output = await tool.execute(tool_input)
            success = output.success
            result_str = json.dumps(output.data) if output.success else f"Error: {output.error}"
        except KeyError:
            success = False
            result_str = f"Unknown tool: {tool_name}"
        except Exception as e:
            success = False
            result_str = f"Tool error: {e}"

        duration_ms = int((time.time() - start) * 1000)

        async with get_session() as db:
            tc_repo = ToolCallRepository(db)
            await tc_repo.log(
                call_id=call_id,
                session_id=self._session_id,
                agent_id=self.agent_id,
                task_id=task_id,
                tool_name=tool_name,
                input_data=tool_input,
                output_data={"result": result_str, "success": success},
                success=success,
                duration_ms=duration_ms,
            )

        return {
            "tool_call_id": tool_call.id,
            "content": result_str,
        }

    # ──────────────────────────────────────────────────────────
    # Message handling
    # ──────────────────────────────────────────────────────────

    async def _on_message(self, message: Message) -> None:
        if message.type == MessageType.REPORT and isinstance(message, ReportMessage):
            await self._pending_reports.put(message)
        elif message.type == MessageType.ESCALATE and isinstance(message, EscalateMessage):
            await self._pending_escalations.put(message)

    async def _wait_for_reports(
        self, expected_count: int, timeout: float | None = None
    ) -> list[ReportMessage]:
        reports: list[ReportMessage] = []
        deadline = asyncio.get_event_loop().time() + (timeout or settings.agent_timeout_seconds)

        while len(reports) < expected_count:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                report = await asyncio.wait_for(self._pending_reports.get(), timeout=remaining)
                reports.append(report)
            except asyncio.TimeoutError:
                break

        return reports

    # ──────────────────────────────────────────────────────────
    # Escalation
    # ──────────────────────────────────────────────────────────

    async def _escalate_budget_warning(self, fraction_remaining: float) -> None:
        if self._ctx.parent_title == "User":
            return
        msg = EscalateMessage(
            from_agent=self.agent_id,
            to_agent=self._ctx.metadata.get("parent_id", ""),
            task_id=self._ctx.metadata.get("current_task_id", ""),
            reason="budget_low",
            detail=(
                f"{self._ctx.title} has {fraction_remaining:.1%} budget remaining. "
                "Continuing but may need reallocation."
            ),
        )
        await self._bus.escalate(msg)

    # ──────────────────────────────────────────────────────────
    # Workspace cleanup
    # ──────────────────────────────────────────────────────────

    def _cleanup_wip(self) -> None:
        """
        Hard guarantee: delete the agent's _wip/ subfolder after every task,
        success or failure. This runs in the framework, not in the LLM —
        the LLM cannot forget or skip it.

        Finds the agent's own dept path as the first permission entry
        that is specific (non-empty, not shared/, has write+delete rights).
        """
        if not self._ctx.workspace_root:
            return
        own_dept: str | None = None
        for perm in self._ctx.workspace_permissions:
            if perm.path and perm.path != "shared/" and perm.can_write and perm.can_delete:
                own_dept = perm.path
                break
        if not own_dept:
            return
        wip_dir = Path(self._ctx.workspace_root) / own_dept.rstrip("/") / "_wip"
        if wip_dir.exists() and wip_dir.is_dir():
            shutil.rmtree(str(wip_dir), ignore_errors=True)

    # ──────────────────────────────────────────────────────────
    # Status + persistence helpers
    # ──────────────────────────────────────────────────────────

    async def _set_status(self, status: AgentStatus, error: str | None = None) -> None:
        await self._registry.update_status(self.agent_id, status)
        async with get_session() as db:
            agent_repo = AgentRepository(db)
            await agent_repo.update_status(self.agent_id, status, error)

    async def _persist_task_done(self, task_id: str, result: str) -> None:
        alloc = self._budget_manager.get_allocation(self.agent_id)
        async with get_session() as db:
            task_repo = TaskRepository(db)
            await task_repo.complete(task_id, result, alloc.used if alloc else 0)

    async def _persist_task_failed(self, task_id: str, error: str) -> None:
        async with get_session() as db:
            task_repo = TaskRepository(db)
            await task_repo.fail(task_id, error)

    def _inventory_dept_files(self) -> list[str]:
        """List deliverable files left on disk in the agent's dept folder (after _wip/ is cleaned)."""
        if not self._ctx.workspace_root:
            return []
        own_dept: str | None = None
        for perm in self._ctx.workspace_permissions:
            if perm.path and perm.path != "shared/" and perm.can_write and perm.can_delete:
                own_dept = perm.path
                break
        if not own_dept:
            return []
        dept_dir = Path(self._ctx.workspace_root) / own_dept.rstrip("/")
        if not dept_dir.exists():
            return []
        root = Path(self._ctx.workspace_root)
        return sorted(
            str(f.relative_to(root))
            for f in dept_dir.rglob("*")
            if f.is_file() and "_wip" not in f.parts
        )

    def _fail_report(self, task: Task, error: str) -> ReportMessage:
        files = self._inventory_dept_files()
        alloc = self._budget_manager.get_allocation(self.agent_id)

        lines = [
            f"**{self._ctx.title} — INTERRUPTED**",
            f"Reason: {error}",
            "",
        ]
        if files:
            lines.append("Files produced before interruption (deliverables kept on disk):")
            for f in files:
                lines.append(f"  - {f}")
        else:
            lines.append("No deliverable files were produced before interruption.")
        lines += [
            "",
            f"Incomplete task: {task.description[:300]}",
            "",
            "Recommended actions for N+1:",
            "  - Retry with a narrower scope using the files above as prior context.",
            "  - Reassign only the remaining work to a new agent.",
            "  - Escalate to CEO if this blocks the team's overall objective.",
        ]

        result = "\n".join(lines)
        return ReportMessage(
            from_agent=self.agent_id,
            to_agent=task.delegated_by,
            task_id=task.id,
            result=result,
            status=TaskStatus.FAILED,
            tokens_used=alloc.used if alloc else 0,
            child_agent_id=self.agent_id,
            issues=[error],
        )

    async def _log_message(self, message: Message, payload: dict) -> None:
        async with get_session() as db:
            msg_repo = MessageRepository(db)
            await msg_repo.log(self._session_id, message, payload)
