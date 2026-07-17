"""Graph builders: researcher subgraph, supervisor subgraph, and the
ODR-style deep researcher core (R-ODR-1, R-ODR-7)."""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from synthora.orchestration.nodes import (
    clarify_interrupt,
    clarify_with_user,
    compress_research,
    final_report_generation,
    researcher_should_continue,
    researcher_step,
    supervisor,
    supervisor_route,
    supervisor_tools,
    write_research_brief,
)
from synthora.orchestration.state import (
    AgentState,
    ResearcherState,
    SupervisorState,
)


def build_researcher_graph():
    """Isolated researcher: ReAct search loop -> compression.

    Compiled without a durable checkpointer: interrupts/resume live only on
    the parent pipeline. Sharing PostgresSaver with the parent has caused
    nested-run failures under a single connection.
    """
    g = StateGraph(ResearcherState)
    g.add_node("researcher_step", researcher_step)
    g.add_node("compress", compress_research)
    g.add_edge(START, "researcher_step")
    g.add_conditional_edges(
        "researcher_step",
        researcher_should_continue,
        {"researcher_step": "researcher_step", "compress": "compress"},
    )
    g.add_edge("compress", END)
    return g.compile()


def build_supervisor_graph():
    """Supervisor loop: plan -> delegate (parallel researchers) -> iterate.

    No durable checkpointer — see ``build_researcher_graph``.
    """
    g = StateGraph(SupervisorState)
    g.add_node("supervisor", supervisor)
    g.add_node("supervisor_tools", supervisor_tools)
    g.add_edge(START, "supervisor")
    g.add_conditional_edges(
        "supervisor",
        supervisor_route,
        {
            "supervisor": "supervisor",
            "supervisor_tools": "supervisor_tools",
            "end": END,
        },
    )
    g.add_edge("supervisor_tools", "supervisor")
    return g.compile()


async def run_supervisor_phase(state: AgentState, config: RunnableConfig) -> dict:
    """Adapter node: runs the supervisor subgraph from the top-level state."""
    supervisor_graph = build_supervisor_graph()
    # Nested graphs need distinct thread ids under the parent checkpointer.
    nested_cfg = {
        **config,
        "configurable": {
            **(config.get("configurable") or {}),
            "thread_id": f"{(config.get('configurable') or {}).get('thread_id', 'run')}:supervisor",
        },
    }
    result = await supervisor_graph.ainvoke(
        {"brief": state["brief"], "research_iterations": 0}, config=nested_cfg
    )
    return {
        "notes": result.get("notes", []),
        "sources": result.get("sources", []),
    }


def build_deep_researcher_core() -> StateGraph:
    """The ODR core: clarify -> brief -> supervised research -> report.

    Returned uncompiled so pipelines can extend it with intelligence nodes.
    """
    g = StateGraph(AgentState)
    g.add_node("clarify", clarify_with_user)
    g.add_node("clarify_wait", clarify_interrupt)
    g.add_node("brief", write_research_brief)
    g.add_node("research", run_supervisor_phase)
    g.add_node("report", final_report_generation)
    g.add_edge(START, "clarify")
    g.add_edge("clarify", "clarify_wait")
    g.add_edge("clarify_wait", "brief")
    g.add_edge("brief", "research")
    g.add_edge("research", "report")
    g.add_edge("report", END)
    return g
