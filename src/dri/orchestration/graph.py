"""
LangGraph team subgraph builder.

Provides a compiled LangGraph StateGraph for use in team-level orchestration
when the LangGraph runtime is preferred over the raw asyncio executor.

The graph implements: supervisor → [parallel workers] → supervisor → END
"""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Send


class TeamMemberResult(TypedDict):
    title: str
    result: str
    success: bool


class TeamState(TypedDict):
    """State passed through the team graph."""

    session_id: str
    manager_id: str
    task_description: str
    task_context: str
    pending_members: list[dict[str, Any]]      # members yet to be spawned
    completed_results: list[TeamMemberResult]  # results collected so far
    final_synthesis: str


def _supervisor_node(state: TeamState) -> list[Send] | dict:
    """
    Supervisor decides: spawn more workers (Send) or move to synthesis (return dict).
    """
    if state["pending_members"]:
        return [
            Send(
                "worker_node",
                {
                    **state,
                    "current_member": member,
                    "pending_members": [],
                },
            )
            for member in state["pending_members"]
        ]
    return {"pending_members": []}


def _worker_node(state: TeamState) -> dict:
    """
    Placeholder: actual agent execution happens in asyncio executor.
    This node exists for LangGraph graph structure; the Executor drives real runs.
    """
    member = state.get("current_member", {})
    return {
        "completed_results": state.get("completed_results", [])
        + [TeamMemberResult(title=member.get("title", ""), result="", success=True)]
    }


def _should_continue(state: TeamState) -> str:
    if state.get("pending_members"):
        return "spawn"
    return "synthesize"


def build_team_graph() -> Any:
    """Build and compile the team LangGraph subgraph."""
    graph = StateGraph(TeamState)
    graph.add_node("supervisor", _supervisor_node)
    graph.add_node("worker_node", _worker_node)
    graph.set_entry_point("supervisor")
    graph.add_conditional_edges(
        "supervisor",
        _should_continue,
        {"spawn": "worker_node", "synthesize": END},
    )
    graph.add_edge("worker_node", "supervisor")
    return graph.compile()


team_graph = build_team_graph()
