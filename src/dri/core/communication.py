"""
Communication bus — typed inter-agent message dispatch.

Agents never call each other directly. They post messages here and await delivery.
This enforces the hierarchical-only communication rule: parent ↔ child, never sibling.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Callable, Awaitable

from dri.core.models import (
    DelegateMessage,
    EscalateMessage,
    Message,
    MessageType,
    ReportMessage,
)


MessageHandler = Callable[[Message], Awaitable[None]]


class CommunicationBus:
    """
    Async pub/sub bus scoped to one session.

    Each agent subscribes with its agent_id. When a message arrives addressed
    to that agent_id, the registered handler coroutine is called.

    Enforces the DRI communication rule: only DELEGATE (parent→child) and
    REPORT/ESCALATE (child→parent) message types are allowed.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[MessageHandler]] = defaultdict(list)
        self._message_log: list[Message] = []
        self._lock = asyncio.Lock()

    # ──────────────────────────────────────────────────────────
    # Subscription
    # ──────────────────────────────────────────────────────────

    def subscribe(self, agent_id: str, handler: MessageHandler) -> None:
        self._handlers[agent_id].append(handler)

    def unsubscribe(self, agent_id: str) -> None:
        self._handlers.pop(agent_id, None)

    # ──────────────────────────────────────────────────────────
    # Sending
    # ──────────────────────────────────────────────────────────

    async def send(self, message: Message) -> None:
        """
        Deliver a message to its recipient.
        Only DELEGATE, REPORT, and ESCALATE types are accepted.
        """
        if message.type not in (MessageType.DELEGATE, MessageType.REPORT, MessageType.ESCALATE):
            raise ValueError(f"Unsupported message type: {message.type}")

        async with self._lock:
            self._message_log.append(message)
            handlers = list(self._handlers.get(message.to_agent, []))

        for handler in handlers:
            await handler(message)

    async def delegate(self, msg: DelegateMessage) -> None:
        await self.send(msg)

    async def report(self, msg: ReportMessage) -> None:
        await self.send(msg)

    async def escalate(self, msg: EscalateMessage) -> None:
        await self.send(msg)

    # ──────────────────────────────────────────────────────────
    # Inspection
    # ──────────────────────────────────────────────────────────

    def message_count(self) -> int:
        return len(self._message_log)

    def messages_for(self, agent_id: str) -> list[Message]:
        return [m for m in self._message_log if m.to_agent == agent_id]

    def messages_from(self, agent_id: str) -> list[Message]:
        return [m for m in self._message_log if m.from_agent == agent_id]
