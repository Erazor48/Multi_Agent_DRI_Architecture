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
                    + "\n\n**Before doing anything else:**\n"
                    "1. Call `file_list` on `shared/` to see what deliverables already exist.\n"
                    "2. If relevant files exist for your task, read them with `file_read` before starting.\n"
                    "3. Build on existing work — do not redo it.\n\n"
                    "Execute this task completely. Use your available tools as needed.\n\n"
                    "**Before writing your final report:**\n"
                    "1. Call `file_list` on your department folder to see what files you actually produced.\n"
                    "2. Only cite files confirmed to exist on disk.\n"
                    "3. If a write failed or produced nothing, report that honestly.\n"
                    "\nReturn a clear, structured result that your manager can use directly."
                ),
            }
        ]
        return await self._agentic_loop(initial_messages, task.id)
