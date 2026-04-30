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
        kpath = self._knowledge_path_str()
        knowledge_note = (
            f"\n\n**Knowledge Update — mandatory final step before report:**\n"
            f"1. Use `file_read` to read `{kpath}/expertise.md` (may not exist yet — that's fine).\n"
            f"2. Use `file_write` to write `{kpath}/expertise.md` with an updated version that includes:\n"
            "   - Patterns and techniques that worked in this task\n"
            "   - Pitfalls and mistakes to avoid\n"
            "   - Domain-specific insights for future similar tasks\n"
            "   Keep it under 60 lines. Write the full updated file (not a diff)."
        ) if kpath else ""

        initial_messages = [
            {
                "role": "user",
                "content": (
                    f"## Your Task\n\n{task.description}"
                    + (f"\n\n## Context\n\n{task.context}" if task.context else "")
                    + "\n\nExecute this task completely. Use your available tools as needed.\n\n"
                    "**Before writing your final report:**\n"
                    "1. Call `file_list` on your department folder to see what files you actually produced.\n"
                    "2. Only cite files confirmed to exist on disk.\n"
                    "3. If a write failed or produced nothing, report that honestly.\n"
                    + knowledge_note
                    + "\nReturn a clear, structured result that your manager can use directly."
                ),
            }
        ]
        return await self._agentic_loop(initial_messages, task.id)
