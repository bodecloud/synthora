"""The four research pipelines (R-PIPE-1..5), composed from ODR core nodes
and STORM intelligence nodes, registered in the pipeline registry.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from synthora.orchestration.checkpoint import get_checkpointer
from synthora.orchestration.context import get_ctx
from synthora.orchestration.intelligence_nodes import (
    autonomous_should_continue,
    bibliography_node,
    citation_verify,
    critic_node,
    discourse_pass,
    gap_finder,
    hypothesize,
    investigate_hypotheses,
    mind_map_upsert,
    outline_node,
    perspective_pass,
    section_write,
)
from synthora.orchestration.nodes import (
    build_citations,
    clarify_interrupt,
    clarify_with_user,
    final_report_generation,
    write_research_brief,
)
from synthora.orchestration.registry import PipelineSpec, pipeline_registry
from synthora.orchestration.state import AgentState

# ---------------------------------------------------------------------------
# fast_research: question -> planning -> search -> summarize -> answer
# ---------------------------------------------------------------------------


async def single_researcher(state: AgentState, config: RunnableConfig) -> dict:
    """One researcher pass over the brief — no supervisor fan-out."""
    from synthora.orchestration.graphs import build_researcher_graph

    ctx = get_ctx(config)
    graph = build_researcher_graph()
    nested_cfg = {
        **config,
        "configurable": {
            **(config.get("configurable") or {}),
            "thread_id": f"{(config.get('configurable') or {}).get('thread_id', 'run')}:researcher",
        },
    }
    result = await graph.ainvoke(
        {"topic": state.get("brief", state["question"]), "tool_calls": 0},
        config=nested_cfg,
    )
    sources = result.get("findings", [])
    return {
        "notes": [result.get("compressed", "")],
        "sources": sources,
        "citations": build_citations(sources, ctx.run_id),
    }


def build_fast_research():
    g = StateGraph(AgentState)
    g.add_node("clarify", clarify_with_user)
    g.add_node("clarify_wait", clarify_interrupt)
    g.add_node("brief", write_research_brief)
    g.add_node("research", single_researcher)
    g.add_node("report", final_report_generation)
    g.add_edge(START, "clarify")
    g.add_edge("clarify", "clarify_wait")
    g.add_edge("clarify_wait", "brief")
    g.add_edge("brief", "research")
    g.add_edge("research", "report")
    g.add_edge("report", END)
    return g.compile(checkpointer=get_checkpointer())


# ---------------------------------------------------------------------------
# deep_research: ODR supervisor + STORM synthesis + criticism (flagship)
# ---------------------------------------------------------------------------


def build_deep_research():
    from synthora.orchestration.graphs import run_supervisor_phase

    g = StateGraph(AgentState)
    g.add_node("clarify", clarify_with_user)
    g.add_node("clarify_wait", clarify_interrupt)
    g.add_node("brief", write_research_brief)
    g.add_node("research", run_supervisor_phase)
    g.add_node("perspectives", perspective_pass)
    g.add_node("discourse", discourse_pass)
    g.add_node("knowledge_map", mind_map_upsert)
    g.add_node("outline", outline_node)
    g.add_node("section_write", section_write)
    g.add_node("critic", critic_node)
    g.add_node("report", final_report_generation)
    g.add_edge(START, "clarify")
    g.add_edge("clarify", "clarify_wait")
    g.add_edge("clarify_wait", "brief")
    g.add_edge("brief", "research")
    g.add_edge("research", "perspectives")
    g.add_edge("perspectives", "discourse")
    g.add_edge("discourse", "knowledge_map")
    g.add_edge("knowledge_map", "outline")
    g.add_edge("outline", "section_write")
    g.add_edge("section_write", "critic")
    g.add_edge("critic", "report")
    g.add_edge("report", END)
    return g.compile(checkpointer=get_checkpointer())


# ---------------------------------------------------------------------------
# open_deep_research: ODR-only supervisor loop (no STORM synthesis stages)
# ---------------------------------------------------------------------------


def build_open_deep_research():
    from synthora.orchestration.graphs import run_supervisor_phase

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
    return g.compile(checkpointer=get_checkpointer())


# ---------------------------------------------------------------------------
# academic_research: lit search -> citation verify -> synthesis -> review
# ---------------------------------------------------------------------------


async def literature_search(state: AgentState, config: RunnableConfig) -> dict:
    """Search academic engines directly (arXiv / Semantic Scholar / etc.)."""
    import asyncio

    ctx = get_ctx(config)
    brief = state.get("brief", state["question"])
    raw = await ctx.planner.complete(
        [
            {
                "role": "system",
                "content": (
                    "Produce 3 academic literature search queries for the brief. "
                    "One per line, keyword style."
                ),
            },
            {"role": "user", "content": brief},
        ]
    )
    queries = [q.strip("-• ").strip() for q in raw.splitlines() if q.strip()][:3] or [
        brief
    ]
    batches = await asyncio.gather(
        *(
            engine.search(q, max_results=5)
            for q in queries
            for engine in ctx.engines
        ),
        return_exceptions=True,
    )
    sources = [
        r for b in batches if not isinstance(b, BaseException) for r in b
    ]
    notes = [
        f"- {r.title} ({(r.metadata or {}).get('year', 'n.d.')}): {r.snippet[:200]}"
        for r in sources[:20]
    ]
    return {
        "sources": sources,
        "notes": ["## Literature found\n" + "\n".join(notes)],
        "citations": build_citations(sources, ctx.run_id),
    }


async def peer_review_critic(state: AgentState, config: RunnableConfig) -> dict:
    """Peer-review style pass over the drafted sections."""
    ctx = get_ctx(config)
    draft = "\n\n".join(state.get("sections", []))
    critique = await ctx.critic.complete(
        [
            {
                "role": "system",
                "content": (
                    "Act as an academic peer reviewer. Assess methodology of the "
                    "synthesis, citation support, balance, and missing literature. "
                    "Give numbered revision points."
                ),
            },
            {
                "role": "user",
                "content": f"Brief: {state.get('brief', state['question'])}\n\n{draft[:12000]}",
            },
        ]
    )
    return {"critique": critique.strip()}


def build_academic_research():
    g = StateGraph(AgentState)
    g.add_node("brief", write_research_brief)
    g.add_node("lit_search", literature_search)
    g.add_node("citation_verify", citation_verify)
    g.add_node("outline", outline_node)
    g.add_node("section_write", section_write)
    g.add_node("peer_review", peer_review_critic)
    g.add_node("report", final_report_generation)
    g.add_node("bibliography", bibliography_node)
    g.add_edge(START, "brief")
    g.add_edge("brief", "lit_search")
    g.add_edge("lit_search", "citation_verify")
    g.add_edge("citation_verify", "outline")
    g.add_edge("outline", "section_write")
    g.add_edge("section_write", "peer_review")
    g.add_edge("peer_review", "report")
    g.add_edge("report", "bibliography")
    g.add_edge("bibliography", END)
    return g.compile(checkpointer=get_checkpointer())


# ---------------------------------------------------------------------------
# autonomous_research: hypothesize -> investigate -> gaps -> loop -> synthesize
# ---------------------------------------------------------------------------


def build_autonomous_research():
    g = StateGraph(AgentState)
    g.add_node("brief", write_research_brief)
    g.add_node("hypothesize", hypothesize)
    g.add_node("investigate", investigate_hypotheses)
    g.add_node("gap_finder", gap_finder)
    g.add_node("knowledge_map", mind_map_upsert)
    g.add_node("report", final_report_generation)
    g.add_edge(START, "brief")
    g.add_edge("brief", "hypothesize")
    g.add_edge("hypothesize", "investigate")
    g.add_edge("investigate", "gap_finder")
    g.add_conditional_edges(
        "gap_finder",
        autonomous_should_continue,
        {"hypothesize": "hypothesize", "synthesize": "knowledge_map"},
    )
    g.add_edge("knowledge_map", "report")
    g.add_edge("report", END)
    return g.compile(checkpointer=get_checkpointer())


# ---------------------------------------------------------------------------
# registration (R-PIPE-1)
# ---------------------------------------------------------------------------

pipeline_registry.register(
    PipelineSpec(
        id="fast_research",
        name="Fast research",
        description="question -> planning -> search -> summarize -> answer",
        builder=build_fast_research,
        tags=["quick"],
    )
)
pipeline_registry.register(
    PipelineSpec(
        id="deep_research",
        name="Deep research",
        description=(
            "planning -> parallel research -> perspectives -> expert discourse -> "
            "knowledge map -> outline -> cited sections -> criticism -> report"
        ),
        builder=build_deep_research,
        tags=["flagship", "storm", "odr"],
    )
)
pipeline_registry.register(
    PipelineSpec(
        id="open_deep_research",
        name="Open Deep Research",
        description=(
            "ODR-equivalent: clarify -> brief -> supervisor parallel researchers -> report"
        ),
        builder=build_open_deep_research,
        tags=["odr", "langgraph"],
    )
)
pipeline_registry.register(
    PipelineSpec(
        id="academic_research",
        name="Academic research",
        description=(
            "literature search -> citation verification -> synthesis -> "
            "peer review -> bibliography"
        ),
        builder=build_academic_research,
        tags=["academic"],
    )
)
pipeline_registry.register(
    PipelineSpec(
        id="autonomous_research",
        name="Autonomous research",
        description=(
            "hypothesize -> investigate -> discover gaps -> new paths -> "
            "knowledge base update -> repeat (bounded)"
        ),
        builder=build_autonomous_research,
        tags=["autonomous", "loop"],
    )
)
