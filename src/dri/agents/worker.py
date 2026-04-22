"""
WorkerAgent — leaf node in the org chart.
Has no children. Executes one task using its tools and reports back.
"""
from __future__ import annotations

from dri.agents.base import BaseAgent
from dri.core.models import Task


class WorkerAgent(BaseAgent):
    """
    A worker does one thing: run its task using its tools, return the result.
    It never spawns children. It never communicates with peers.
    """

    async def _run_task(self, task: Task) -> str:
        initial_messages = [
            {
                "role": "user",
                "content": (
                    f"## Your Task\n\n{task.description}"
                    + (f"\n\n## Context\n\n{task.context}" if task.context else "")
                    + "\n\nExecute this task completely. Use your available tools as needed. "
                    "Return a clear, structured result that your manager can use directly."
                ),
            }
        ]
        return await self._agentic_loop(initial_messages, task.id)
