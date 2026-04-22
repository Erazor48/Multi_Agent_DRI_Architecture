"""
BaseAgent — shared logic for all agent types.

Handles:
- LLM calls (with prompt caching, budget enforcement, retry)
- Tool dispatch (receive tool_use block → execute → return result)
- Status lifecycle management
- Message handling (subscribe to bus, dispatch incoming messages)
- DB persistence (via repositories)

Concrete agents (RootAgent, ManagerAgent, WorkerAgent) override
`_run_task()` to implement their specific behavior.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from dri.config.settings import settings
from dri.core.budget import BudgetExceededError, BudgetManager, BudgetWarning
from dri.core.communication import CommunicationBus
from dri.core.memory import ContextPacket
from dri.core.models import (
    AgentStatus,
    DelegateMessage,
    EscalateMessage,
    Message,
    MessageType,
    ReportMessage,
    Task,
    TaskStatus,
)
from dri.core.registry import AgentRegistry
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
    ) -> None:
        self._ctx = context
        self._session_id = session_id
        self._registry = registry
        self._bus = bus
        self._budget_manager = budget_manager
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = context.model or settings.default_model
        self._pending_reports: asyncio.Queue[ReportMessage] = asyncio.Queue()
        self._pending_escalations: asyncio.Queue[EscalateMessage] = asyncio.Queue()

        # Subscribe to incoming messages
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
            await self._set_status(AgentStatus.DONE)
            report = ReportMessage(
                from_agent=self.agent_id,
                to_agent=task.delegated_by,
                task_id=task.id,
                result=result,
                status=TaskStatus.DONE,
                tokens_used=self._budget_manager.get_allocation(self.agent_id).used
                if self._budget_manager.get_allocation(self.agent_id)
                else 0,
                child_agent_id=self.agent_id,
            )
            await self._persist_task_done(task.id, result)
            return report

        except asyncio.TimeoutError:
            error = f"Agent {self._ctx.title} timed out after {settings.agent_timeout_seconds}s."
            await self._set_status(AgentStatus.FAILED, error=error)
            await self._persist_task_failed(task.id, error)
            return self._fail_report(task, error)

        except BudgetExceededError as e:
            error = str(e)
            await self._set_status(AgentStatus.FAILED, error=error)
            await self._persist_task_failed(task.id, error)
            return self._fail_report(task, error)

        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            await self._set_status(AgentStatus.FAILED, error=error)
            await self._persist_task_failed(task.id, error)
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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def _call_llm(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        estimated_tokens: int = 4000,
    ) -> anthropic.types.Message:
        """
        Make a single LLM call with budget enforcement and prompt caching.
        All LLM calls in the system go through this method — no exceptions.
        """
        try:
            await self._budget_manager.check_and_deduct(self.agent_id, estimated_tokens)
        except BudgetWarning as w:
            await self._escalate_budget_warning(w.fraction_remaining)
            # Budget warning is non-blocking — we continue after escalating

        system_prompt = self._ctx.to_system_prompt()

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": settings.max_tokens_per_response,
            "system": [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},  # prompt caching
                }
            ],
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        response = await self._client.messages.create(**kwargs)

        # Reconcile actual vs estimated token usage
        actual_tokens = response.usage.input_tokens + response.usage.output_tokens
        await self._budget_manager.record_actual(self.agent_id, estimated_tokens, actual_tokens)
        await self._registry.add_tokens(self.agent_id, actual_tokens)

        # Persist budget deduction to DB
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

        for _ in range(20):  # max 20 tool call rounds
            response = await self._call_llm(messages, tools=tool_specs or None)

            # Collect all content blocks
            assistant_content: list[dict[str, Any]] = []
            tool_uses: list[dict[str, Any]] = []
            final_text = ""

            for block in response.content:
                if block.type == "text":
                    final_text = block.text
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    tool_uses.append(block)
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

            messages.append({"role": "assistant", "content": assistant_content})

            if response.stop_reason == "end_turn" or not tool_uses:
                return final_text

            # Execute all tool calls and collect results
            tool_results = await asyncio.gather(
                *[self._execute_tool(tu, task_id) for tu in tool_uses]
            )

            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": result["tool_use_id"],
                        "content": result["content"],
                    }
                    for result in tool_results
                ],
            })

        return final_text or "Maximum tool call rounds reached."

    async def _execute_tool(self, tool_use_block: Any, task_id: str) -> dict[str, Any]:
        """Execute one tool call, log it, and return the result block."""
        call_id = str(uuid.uuid4())
        tool_name = tool_use_block.name
        tool_input = tool_use_block.input or {}
        start = time.time()

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
            "tool_use_id": tool_use_block.id,
            "content": result_str,
        }

    # ──────────────────────────────────────────────────────────
    # Message handling
    # ──────────────────────────────────────────────────────────

    async def _on_message(self, message: Message) -> None:
        """Route incoming messages to the appropriate queue."""
        if message.type == MessageType.REPORT and isinstance(message, ReportMessage):
            await self._pending_reports.put(message)
        elif message.type == MessageType.ESCALATE and isinstance(message, EscalateMessage):
            await self._pending_escalations.put(message)

    async def _wait_for_reports(
        self, expected_count: int, timeout: float | None = None
    ) -> list[ReportMessage]:
        """Wait until we have `expected_count` report messages from children."""
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
        if self._ctx.parent_title == "User":  # root agent — nowhere to escalate
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
    # Status + persistence helpers
    # ──────────────────────────────────────────────────────────

    async def _set_status(self, status: AgentStatus, error: str | None = None) -> None:
        await self._registry.update_status(self.agent_id, status)
        async with get_session() as db:
            agent_repo = AgentRepository(db)
            await agent_repo.update_status(self.agent_id, status, error)

    async def _persist_task_done(self, task_id: str, result: str) -> None:
        used = (
            self._budget_manager.get_allocation(self.agent_id).used
            if self._budget_manager.get_allocation(self.agent_id)
            else 0
        )
        async with get_session() as db:
            task_repo = TaskRepository(db)
            await task_repo.complete(task_id, result, used)

    async def _persist_task_failed(self, task_id: str, error: str) -> None:
        async with get_session() as db:
            task_repo = TaskRepository(db)
            await task_repo.fail(task_id, error)

    def _fail_report(self, task: Task, error: str) -> ReportMessage:
        return ReportMessage(
            from_agent=self.agent_id,
            to_agent=task.delegated_by,
            task_id=task.id,
            result="",
            status=TaskStatus.FAILED,
            tokens_used=0,
            child_agent_id=self.agent_id,
            issues=[error],
        )

    async def _log_message(self, message: Message, payload: dict) -> None:
        async with get_session() as db:
            msg_repo = MessageRepository(db)
            await msg_repo.log(self._session_id, message, payload)
