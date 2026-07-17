"""LangGraph nodes wrapping the STORM/Co-STORM intelligence layer (U4 → U5).

These operate on AgentState so any pipeline can compose them.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from synthora.core.events import RunEventType
from synthora.core.models import OutlineNode
from synthora.intelligence.discourse import DiscourseManager
from synthora.intelligence.knowledge_map import KnowledgeMap
from synthora.intelligence.outline import (
    OutlineBuilder,
    SectionWriter,
    flatten_sections,
)
from synthora.intelligence.perspectives import PerspectiveEngine
from synthora.orchestration.context import get_ctx
from synthora.orchestration.nodes import build_citations
from synthora.orchestration.state import AgentState


async def perspective_pass(state: AgentState, config: RunnableConfig) -> dict:
    """Discover expert perspectives and seed guided questions (R-STORM-1)."""
    ctx = get_ctx(config)
    await ctx.emit(RunEventType.NODE_STARTED, "Discovering perspectives", node="perspectives")
    context = "\n".join(state.get("notes", [])[:3])
    engine = PerspectiveEngine(ctx.planner)
    brief = state.get("brief", state["question"])
    has_wikipedia = any(
        getattr(e, "name", "") == "wikipedia" for e in (ctx.engines or [])
    )
    if has_wikipedia:
        perspectives = await engine.mine_from_wikipedia_toc(
            brief,
            count=ctx.config.num_perspectives,
        )
    else:
        perspectives = await engine.discover(
            brief,
            count=ctx.config.num_perspectives,
            context=context[:3000],
        )
    guided: dict[str, list[str]] = {}
    for p in perspectives:
        questions = await engine.generate_questions(p, brief, count=3)
        guided[p.name] = questions
        await ctx.emit(
            RunEventType.PERSPECTIVE_CREATED,
            p.name,
            node="perspectives",
            payload={"focus": p.focus, "questions": questions},
        )
    meta = {
        **state.get("metadata", {}),
        "guided_questions": guided,
        "perspective_source": "wikipedia_toc" if has_wikipedia else "discover",
    }
    return {"perspectives": perspectives, "metadata": meta}


async def discourse_pass(state: AgentState, config: RunnableConfig) -> dict:
    """Run the Co-STORM roundtable seeded with research sources (R-STORM-4)."""
    ctx = get_ctx(config)
    await ctx.emit(RunEventType.NODE_STARTED, "Expert roundtable", node="discourse")
    from synthora.intelligence.embeddings import make_embedding_similarity

    manager = DiscourseManager(
        ctx.researcher,
        engines=ctx.engines,
        experts_per_round=2,
        alpha=ctx.config.moderator_alpha,
        similarity=make_embedding_similarity(),
    )
    topic = state.get("brief", state["question"])
    perspectives = state.get("perspectives", [])
    if state.get("sources"):
        manager.add_evidence(state.get("sources", []))

    notes = state.get("notes") or []
    extra = ctx.config.extra or {}
    # Warm-start when notes are empty, or whenever extra.warm_start is True (default).
    if not notes or extra.get("warm_start", True):
        warm_questions = await manager.warm_start(topic, perspectives)
        for q in warm_questions:
            manager.inject_user_turn(f"[warm-start] {q}")
    if extra.get("pure_rag"):
        await manager.pure_rag_turn(topic)
    if extra.get("simulated_user"):
        await manager.simulated_user_turn(topic)

    guided = (state.get("metadata") or {}).get("guided_questions") or {}
    for msg in ctx.steering:
        manager.inject_user_turn(msg)
    turns = await manager.run_discourse(
        topic,
        perspectives,
        max_turns=ctx.config.max_discourse_turns,
        seed_evidence=state.get("sources", []),
        guided_questions=guided,
    )
    for t in turns:
        await ctx.emit(
            RunEventType.DISCOURSE_TURN,
            f"{t.speaker}: {t.utterance[:120]}",
            node="discourse",
            payload={"speaker": t.speaker, "role": t.role, "intent": t.intent},
        )
    extra_sources = manager.evidence_pool
    return {"discourse": turns, "sources": extra_sources}


async def mind_map_upsert(state: AgentState, config: RunnableConfig) -> dict:
    """Insert all evidence into a hierarchical knowledge map and reorganize
    overloaded nodes (R-STORM-3)."""
    ctx = get_ctx(config)
    await ctx.emit(RunEventType.NODE_STARTED, "Building knowledge map", node="knowledge_map")
    from synthora.intelligence.embeddings import make_embedding_similarity

    kmap = KnowledgeMap(
        state.get("brief", state["question"])[:80],
        capacity=ctx.config.knowledge_node_capacity,
        similarity=make_embedding_similarity(),
    )
    citations = state.get("citations") or build_citations(
        state.get("sources", []), ctx.run_id
    )
    for c in citations:
        kmap.insert(c)
    await kmap.reorganize(ctx.compressor)
    await ctx.emit(
        RunEventType.KNOWLEDGE_UPDATED,
        f"{len(kmap.nodes)} concepts",
        node="knowledge_map",
        payload={"outline": kmap.to_outline_text()},
    )
    return {
        "knowledge_nodes": list(kmap.nodes.values()),
        "knowledge_edges": kmap.edges,
        "citations": citations,
        "metadata": {**state.get("metadata", {}), "knowledge_map_outline": kmap.to_outline_text()},
    }


async def outline_node(state: AgentState, config: RunnableConfig) -> dict:
    """Outline-first structuring (R-STORM-5)."""
    ctx = get_ctx(config)
    await ctx.emit(RunEventType.NODE_STARTED, "Designing outline", node="outline")
    transcript = "\n".join(
        f"{t.speaker}: {t.utterance}" for t in state.get("discourse", [])
    )
    builder = OutlineBuilder(ctx.writer)
    outline = await builder.build(
        state.get("brief", state["question"]),
        notes="\n\n".join(state.get("notes", [])),
        discourse_transcript=transcript,
    )
    await ctx.emit(
        RunEventType.OUTLINE_READY,
        outline.title,
        node="outline",
        payload={"sections": [s.title for s in flatten_sections(outline)]},
    )
    return {"outline": outline}


async def section_write(state: AgentState, config: RunnableConfig) -> dict:
    """Section-by-section cited writing + polish pass (R-STORM-5)."""
    ctx = get_ctx(config)
    outline = state.get("outline") or OutlineNode(title=state["question"])
    citations = state.get("citations") or build_citations(
        state.get("sources", []), ctx.run_id
    )
    from synthora.intelligence.embeddings import default_hash_embeddings

    writer = SectionWriter(ctx.writer, embeddings=default_hash_embeddings())
    notes = "\n\n".join(state.get("notes", []))
    brief = state.get("brief", state["question"])
    sections: list[str] = []
    for section in flatten_sections(outline):
        text = await writer.write_section(
            section,
            brief=brief,
            citations=citations,
            notes=notes,
        )
        sections.append(text)
        await ctx.emit(
            RunEventType.SECTION_WRITTEN, section.title, node="section_write"
        )
    draft = "\n\n".join(sections)
    polished = await writer.polish(draft, brief=brief)
    await ctx.emit(RunEventType.NODE_FINISHED, "Polished report draft", node="polish")
    return {
        "sections": sections,
        "citations": citations,
        "report": polished,
    }


async def critic_node(state: AgentState, config: RunnableConfig) -> dict:
    """Criticism pass before the final report (deep pipeline, R-PIPE-3)."""
    ctx = get_ctx(config)
    draft = "\n\n".join(state.get("sections", [])) or "\n\n".join(
        state.get("notes", [])
    )
    critique = await ctx.critic.complete(
        [
            {
                "role": "system",
                "content": (
                    "You are a rigorous reviewer. Critique this research draft: "
                    "unsupported claims, missing angles, weak citations, logical "
                    "gaps. Be specific and actionable in at most 10 bullet points."
                ),
            },
            {
                "role": "user",
                "content": f"Brief: {state.get('brief', state['question'])}\n\n{draft[:12000]}",
            },
        ]
    )
    await ctx.emit(RunEventType.CRITIQUE, critique[:200], node="critic")
    return {"critique": critique.strip()}


# ---------------------------------------------------------------------------
# Academic pipeline nodes (R-PIPE-4)
# ---------------------------------------------------------------------------


async def citation_verify(state: AgentState, config: RunnableConfig) -> dict:
    """Verify citations: does the source snippet actually support its use?

    LLM cross-checks each citation's snippet against the research brief;
    low-relevance sources get confidence lowered and verified=False.
    """
    ctx = get_ctx(config)
    citations = state.get("citations") or build_citations(
        state.get("sources", []), ctx.run_id
    )
    if not citations:
        return {"citations": []}
    listing = "\n".join(
        f"{c.index}: {c.title} — {c.snippet[:200]}" for c in citations[:30]
    )
    raw = await ctx.critic.complete(
        [
            {
                "role": "system",
                "content": (
                    "You verify sources for an academic report. For each numbered "
                    "source decide if it is substantive and relevant to the brief. "
                    'Reply JSON: {"verified": [1, 4, ...], "rejected": [2, ...]}'
                ),
            },
            {
                "role": "user",
                "content": f"Brief: {state.get('brief', state['question'])}\n\nSources:\n{listing}",
            },
        ]
    )
    from synthora.core.parsing import parse_json_response

    parsed = parse_json_response(raw) or {}
    verified = set(parsed.get("verified", []))
    rejected = set(parsed.get("rejected", []))
    for c in citations:
        if c.index in verified:
            c.verified = True
        elif c.index in rejected:
            c.verified = False
            c.confidence = min(c.confidence, 0.3)
        else:
            c.verified = True  # unknown -> keep, don't lose sources
    return {"citations": citations}


async def bibliography_node(state: AgentState, config: RunnableConfig) -> dict:
    """Append a formatted bibliography to the report (R-PIPE-4)."""
    citations = [c for c in state.get("citations", []) if c.verified]
    lines = ["", "## Bibliography", ""]
    for c in sorted(citations, key=lambda c: c.index or 0):
        meta = ""
        lines.append(f"[{c.index}] {c.title}{meta}. Available at: {c.url}")
    report = state.get("report", "")
    return {"report": report + "\n" + "\n".join(lines)}


# ---------------------------------------------------------------------------
# Autonomous pipeline nodes (R-PIPE-5)
# ---------------------------------------------------------------------------


async def hypothesize(state: AgentState, config: RunnableConfig) -> dict:
    """Generate testable hypotheses / research paths from the brief + gaps."""
    ctx = get_ctx(config)
    gaps = state.get("gaps", [])
    prior = state.get("hypotheses", [])
    prompt = f"Brief: {state.get('brief', state['question'])}"
    if gaps:
        prompt += "\n\nKnown knowledge gaps:\n" + "\n".join(f"- {g}" for g in gaps)
    if prior:
        prompt += "\n\nAlready investigated:\n" + "\n".join(f"- {h}" for h in prior)
    raw = await ctx.planner.complete(
        [
            {
                "role": "system",
                "content": (
                    "Generate 2-3 concrete, investigable hypotheses or research "
                    "paths that would best advance understanding. Avoid paths "
                    "already investigated. Return one per line."
                ),
            },
            {"role": "user", "content": prompt},
        ]
    )
    new = [h.strip("-• ").strip() for h in raw.splitlines() if h.strip()][:3]
    return {"hypotheses": prior + new, "metadata": {**state.get("metadata", {}), "current_hypotheses": new}}


async def gap_finder(state: AgentState, config: RunnableConfig) -> dict:
    """Discover knowledge gaps from notes (moderator-style unknown unknowns)."""
    ctx = get_ctx(config)
    notes = "\n\n".join(state.get("notes", []))[-8000:]
    raw = await ctx.critic.complete(
        [
            {
                "role": "system",
                "content": (
                    "Identify the most important unanswered questions and knowledge "
                    "gaps given the research so far. Return one gap per line, max 5."
                ),
            },
            {
                "role": "user",
                "content": f"Brief: {state.get('brief', state['question'])}\n\nNotes:\n{notes}",
            },
        ]
    )
    gaps = [g.strip("-• ").strip() for g in raw.splitlines() if g.strip()][:5]
    await ctx.emit(
        RunEventType.KNOWLEDGE_UPDATED,
        f"{len(gaps)} gaps found",
        node="gap_finder",
        payload={"gaps": gaps},
    )
    return {"gaps": gaps}


async def investigate_hypotheses(state: AgentState, config: RunnableConfig) -> dict:
    """Investigate the current hypotheses via the supervisor subgraph."""
    from synthora.orchestration.graphs import build_supervisor_graph

    current = state.get("metadata", {}).get("current_hypotheses") or state.get(
        "hypotheses", []
    )[-3:]
    brief = state.get("brief", state["question"])
    focus = "\n".join(f"- {h}" for h in current)
    supervisor_graph = build_supervisor_graph()
    nested_cfg = {
        **config,
        "configurable": {
            **(config.get("configurable") or {}),
            "thread_id": f"{(config.get('configurable') or {}).get('thread_id', 'run')}:auto-sup",
        },
    }
    result = await supervisor_graph.ainvoke(
        {
            "brief": f"{brief}\n\nInvestigate specifically:\n{focus}",
            "research_iterations": 0,
        },
        config=nested_cfg,
    )
    return {
        "notes": result.get("notes", []),
        "sources": result.get("sources", []),
        "cycle": state.get("cycle", 0) + 1,
    }


def autonomous_should_continue(state: AgentState, config: RunnableConfig) -> str:
    """Bounded loop control (R-PIPE-5)."""
    ctx = get_ctx(config)
    if state.get("cycle", 0) >= ctx.config.max_autonomous_cycles:
        return "synthesize"
    if not state.get("gaps"):
        return "synthesize"
    return "hypothesize"
