"""Core ODR-style nodes: clarify, brief, supervisor loop, researcher loop,
compression, and final report (R-ODR-2..5).
"""

from __future__ import annotations

import asyncio

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt
from synthora.core.events import RunEventType
from synthora.core.models import Citation, SearchResult
from synthora.orchestration.context import get_ctx, parse_json_response
from synthora.orchestration.state import (
    AgentState,
    ResearcherState,
    SupervisorState,
)
from synthora.orchestration.token_limits import complete_with_retry

# --------------------------------------------------------------------------
# Scope phase
# --------------------------------------------------------------------------


async def clarify_with_user(state: AgentState, config: RunnableConfig) -> dict:
    """Decide whether clarification is needed (R-ODR-2).

    Split from the interrupt itself so LangGraph resume re-entry does not
    re-call the planner (nodes re-run from the top on ``Command(resume=...)``).
    """
    ctx = get_ctx(config)
    if not ctx.config.allow_clarification or state.get("clarification"):
        return {}
    if state.get("pending_clarification"):
        return {}
    raw = await ctx.planner.complete(
        [
            {
                "role": "system",
                "content": (
                    "You scope research requests. If the question is clear enough "
                    'to research, reply {"clear": true}. Otherwise reply '
                    '{"clear": false, "question": "<one clarifying question>"}.'
                ),
            },
            {"role": "user", "content": state["question"]},
        ]
    )
    parsed = parse_json_response(raw) or {"clear": True}
    if parsed.get("clear", True):
        return {}
    question = str(parsed.get("question", "") or "Can you clarify your research goal?")
    await ctx.emit(RunEventType.INTERRUPT, question, node="clarify")
    return {"pending_clarification": question}


async def clarify_interrupt(state: AgentState, config: RunnableConfig) -> dict:
    """Pause for the user's answer when ``pending_clarification`` is set."""
    question = state.get("pending_clarification")
    if not question or state.get("clarification"):
        return {}
    answer = interrupt({"question": question})
    return {"clarification": str(answer), "pending_clarification": None}


async def write_research_brief(state: AgentState, config: RunnableConfig) -> dict:
    """Compress the question (+ clarification + steering) into a brief."""
    ctx = get_ctx(config)
    await ctx.emit(RunEventType.NODE_STARTED, "Writing research brief", node="brief")
    parts = [f"Question: {state['question']}"]
    if state.get("clarification"):
        parts.append(f"Clarification: {state['clarification']}")
    if ctx.steering:
        parts.append("User steering: " + "; ".join(ctx.steering))
    extra = ctx.config.extra or {}
    parent_brief = str(extra.get("parent_brief") or "").strip()
    parent_notes = str(extra.get("parent_notes_snippet") or "").strip()
    chat_history = str(extra.get("chat_history") or "").strip()
    if parent_brief:
        parts.append(f"Prior research brief (follow-up context):\n{parent_brief}")
    if parent_notes:
        parts.append(f"Prior research notes (excerpt):\n{parent_notes}")
    if chat_history:
        parts.append(f"Prior conversation in this session:\n{chat_history}")
    brief = await ctx.planner.complete(
        [
            {
                "role": "system",
                "content": (
                    "Rewrite the research request as a detailed, self-contained "
                    "research brief. State the core question, scope boundaries, "
                    "and what a complete answer must cover. When prior research or "
                    "chat context is provided, build on it rather than repeating "
                    "it. Reply with the brief only."
                ),
            },
            {"role": "user", "content": "\n".join(parts)},
        ]
    )
    await ctx.emit(RunEventType.NODE_FINISHED, "Research brief ready", node="brief")
    return {"brief": brief.strip()}


# --------------------------------------------------------------------------
# Researcher subgraph (isolated ReAct loop) — R-ODR-4
# --------------------------------------------------------------------------


async def researcher_step(state: ResearcherState, config: RunnableConfig) -> dict:
    """One ReAct step: decide next search, MCP tool call, or finish."""
    ctx = get_ctx(config)
    topic = state["topic"]
    calls = state.get("tool_calls", 0)
    findings_summary = "\n".join(
        f"- {r.title}: {r.snippet[:150]}" for r in state.get("findings", [])[-8:]
    )
    mcp_tools = list(getattr(ctx, "mcp_tools", None) or [])
    tool_names = [getattr(t, "name", str(t)) for t in mcp_tools]
    tool_hint = ""
    if tool_names:
        tool_hint = (
            f"\nMCP tools available: {', '.join(tool_names)}. "
            'To call one reply JSON: {"action": "tool", "tool": "<name>", '
            '"args": {...}, "reflection": "..."}.'
        )
    raw = await ctx.researcher.complete(
        [
            {
                "role": "system",
                "content": (
                    "You are a researcher with a search tool. Given the topic and "
                    "findings so far, either issue the next search or finish.\n"
                    'Reply JSON: {"action": "search", "query": "...", '
                    '"reflection": "..."} or {"action": "complete", '
                    f'"reflection": "..."}}.{tool_hint}'
                ),
            },
            {
                "role": "user",
                "content": f"Topic: {topic}\nSearches used: {calls}/"
                f"{ctx.config.max_react_tool_calls}\nFindings:\n"
                f"{findings_summary or '(none yet)'}"
                + (
                    "\nUser steering: " + "; ".join(ctx.steering)
                    if ctx.steering
                    else ""
                ),
            },
        ]
    )
    decision = parse_json_response(raw) or {"action": "search", "query": topic}
    if decision.get("action") == "complete" and calls > 0:
        return {"done": True}

    if decision.get("action") == "tool" and mcp_tools:
        tool_name = str(decision.get("tool") or decision.get("name") or "")
        args = decision.get("args") or decision.get("arguments") or {}
        if not isinstance(args, dict):
            args = {}
        matched = next(
            (t for t in mcp_tools if getattr(t, "name", "") == tool_name), None
        )
        content = f"unknown tool: {tool_name}"
        if matched is not None and hasattr(matched, "ainvoke"):
            try:
                content = await matched.ainvoke(args)
            except Exception as exc:  # noqa: BLE001
                content = f"tool error: {exc}"
        result = SearchResult(
            url=f"mcp://{tool_name}",
            title=f"MCP:{tool_name}",
            snippet=str(content)[:500],
            content=str(content),
            engine="mcp",
            score=1.0,
            metadata={"tool": tool_name, "args": args},
        )
        note = decision.get("reflection", "")
        await ctx.emit(
            RunEventType.SOURCE_FOUND,
            result.title,
            node="researcher",
            payload={"url": result.url, "tool": tool_name},
        )
        return {
            "tool_calls": calls + 1,
            "findings": [result],
            "researcher_notes": [note] if note else [],
        }

    query = decision.get("query") or topic
    await ctx.emit(
        RunEventType.SEARCH_ISSUED, query, node="researcher", payload={"topic": topic}
    )
    if ctx.strategy is not None:
        results = await ctx.strategy.run(
            query, engines=ctx.engines, llm=ctx.researcher
        )
    else:
        batches = await asyncio.gather(
            *(e.search(query, max_results=5) for e in ctx.engines),
            return_exceptions=True,
        )
        results = [
            r
            for b in batches
            if not isinstance(b, BaseException)
            for r in b
        ]
    for r in results[:5]:
        await ctx.emit(
            RunEventType.SOURCE_FOUND,
            r.title or r.url,
            node="researcher",
            payload={"url": r.url},
        )
    note = decision.get("reflection", "")
    return {
        "tool_calls": calls + 1,
        "findings": results,
        "researcher_notes": [note] if note else [],
    }


def researcher_should_continue(state: ResearcherState, config: RunnableConfig) -> str:
    ctx = get_ctx(config)
    if state.get("done"):
        return "compress"
    calls = state.get("tool_calls", 0)
    if calls >= ctx.config.max_react_tool_calls:
        return "compress"
    if calls > 0 and not state.get("findings"):
        return "compress"  # searches are returning nothing; stop burning budget
    return "researcher_step"


async def compress_research(state: ResearcherState, config: RunnableConfig) -> dict:
    """Compress raw tool output into clean notes before returning to the
    supervisor (context isolation, R-ODR-4)."""
    ctx = get_ctx(config)
    corpus = "\n\n".join(
        f"[{i + 1}] {r.title}\nURL: {r.url}\n{(r.content or r.snippet)[: ctx.config.max_content_length // 10]}"
        for i, r in enumerate(state.get("findings", [])[:20])
    )
    compressed = await complete_with_retry(
        ctx.compressor,
        [
            {
                "role": "system",
                "content": (
                    "Compress these research findings into dense factual notes for "
                    "the topic. Preserve every load-bearing fact, number, and "
                    "attribution. Keep [n] source markers next to claims."
                ),
            },
            {
                "role": "user",
                "content": f"Topic: {state['topic']}\n\n{corpus or '(no findings)'}",
            },
        ],
        truncate_user_to=ctx.config.max_content_length,
    )
    return {"compressed": compressed.strip()}


# --------------------------------------------------------------------------
# Supervisor subgraph — R-ODR-3
# --------------------------------------------------------------------------

SUPERVISOR_SYSTEM = """You are a research supervisor delegating to parallel researchers.
Decide the next action based on the brief and notes collected so far.

Reply with exactly one JSON object:
- {"action": "think", "reflection": "<strategic reasoning about gaps>"}
- {"action": "conduct_research", "topics": ["<subtopic 1>", "<subtopic 2>", ...]}
- {"action": "research_complete", "reason": "<why coverage is sufficient>"}

Rules: prefer 2-4 focused parallel topics per conduct_research call; call
research_complete once the notes can support a comprehensive answer."""


async def supervisor(state: SupervisorState, config: RunnableConfig) -> dict:
    ctx = get_ctx(config)
    iterations = state.get("research_iterations", 0)
    notes = state.get("notes", [])
    notes_block = "\n\n".join(notes[-10:]) or "(no research yet)"
    raw = await ctx.planner.complete(
        [
            {"role": "system", "content": SUPERVISOR_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Brief:\n{state['brief']}\n\nIteration: {iterations}/"
                    f"{ctx.config.max_researcher_iterations}\n\nNotes so far:\n"
                    f"{notes_block}"
                ),
            },
        ]
    )
    decision = parse_json_response(raw) or {
        "action": "conduct_research",
        "topics": [state["brief"][:200]],
    }
    return {
        "supervisor_messages": [decision],
        "research_iterations": iterations + 1,
    }


def supervisor_route(state: SupervisorState, config: RunnableConfig) -> str:
    ctx = get_ctx(config)
    decisions = state.get("supervisor_messages", [])
    last = decisions[-1] if decisions else {}
    if state.get("research_iterations", 0) > ctx.config.max_researcher_iterations:
        return "end"
    action = last.get("action")
    if action == "research_complete":
        return "end"
    if action == "think":
        return "supervisor"
    return "supervisor_tools"


async def supervisor_tools(state: SupervisorState, config: RunnableConfig) -> dict:
    """Execute ConductResearch: run researcher subgraphs in parallel with a
    concurrency cap (R-ODR-4). Overflow topics beyond the cap are dropped
    with an error note, mirroring ODR."""
    from synthora.orchestration.graphs import build_researcher_graph

    ctx = get_ctx(config)
    last = state["supervisor_messages"][-1]
    topics = [t for t in last.get("topics", []) if isinstance(t, str) and t.strip()]
    if not topics:
        return {}

    cap = ctx.config.max_concurrent_research_units
    overflow = topics[cap:]
    topics = topics[:cap]
    await ctx.emit(
        RunEventType.NODE_STARTED,
        f"Dispatching {len(topics)} parallel researchers",
        node="supervisor_tools",
        payload={"topics": topics},
    )

    researcher_graph = build_researcher_graph()
    results = await asyncio.gather(
        *(
            researcher_graph.ainvoke(
                {"topic": topic, "tool_calls": 0},
                config={
                    **config,
                    "configurable": {
                        **(config.get("configurable") or {}),
                        "thread_id": (
                            f"{(config.get('configurable') or {}).get('thread_id', 'run')}"
                            f":researcher:{i}"
                        ),
                    },
                },
            )
            for i, topic in enumerate(topics)
        ),
        return_exceptions=True,
    )

    notes: list[str] = []
    sources: list[SearchResult] = []
    for topic, result in zip(topics, results):
        if isinstance(result, BaseException):
            notes.append(f"[research error] {topic}: {result}")
            continue
        compressed = result.get("compressed", "")
        if compressed:
            notes.append(f"## {topic}\n{compressed}")
        sources.extend(result.get("findings", []))
    for topic in overflow:
        notes.append(
            f"[capacity error] topic '{topic}' exceeded "
            f"max_concurrent_research_units={cap} and was not researched"
        )
    return {"notes": notes, "sources": sources}


# --------------------------------------------------------------------------
# Write phase
# --------------------------------------------------------------------------


def build_citations(sources: list[SearchResult], run_id: str) -> list[Citation]:
    """Deduplicate sources into indexed citations."""
    seen: dict[str, Citation] = {}
    for s in sources:
        key = s.url.rstrip("/")
        if key and key not in seen:
            seen[key] = Citation(
                run_id=run_id,
                url=s.url,
                title=s.title,
                snippet=s.snippet[:300],
                confidence=min(1.0, max(0.1, s.score or 0.5)),
                index=len(seen) + 1,
            )
    return list(seen.values())


async def final_report_generation(state: AgentState, config: RunnableConfig) -> dict:
    """One-shot report from brief + notes (ODR write phase, R-ODR-1)."""
    ctx = get_ctx(config)
    await ctx.emit(RunEventType.NODE_STARTED, "Writing final report", node="report")
    existing = state.get("citations") or []
    citations = existing or build_citations(state.get("sources", []), ctx.run_id)
    sources_block = "\n".join(
        f"[{c.index}] {c.title} — {c.url}" for c in citations[:40]
    )
    notes_block = "\n\n".join(state.get("notes", []))
    sections_block = "\n\n".join(state.get("sections", []))
    critique = state.get("critique", "")
    polished_draft = state.get("report", "")
    prompt_parts = [f"Research brief:\n{state.get('brief', state['question'])}"]
    if polished_draft:
        prompt_parts.append(f"Polished draft to refine:\n{polished_draft[:ctx.config.max_content_length]}")
    elif sections_block:
        prompt_parts.append(f"Drafted sections:\n{sections_block}")
    if notes_block:
        prompt_parts.append(f"Research notes:\n{notes_block[:ctx.config.max_content_length]}")
    if critique:
        prompt_parts.append(f"Reviewer critique to address:\n{critique}")
    prompt_parts.append(f"Available sources:\n{sources_block}")
    report = await complete_with_retry(
        ctx.writer,
        [
            {
                "role": "system",
                "content": (
                    "Write the final research report in Markdown. Use clear section "
                    "headings, cite claims with [n] markers matching the source "
                    "list, and end with a '## Sources' section listing the cited "
                    "sources."
                ),
            },
            {"role": "user", "content": "\n\n".join(prompt_parts)},
        ],
        temperature=0.4,
        truncate_user_to=ctx.config.max_content_length,
    )
    await ctx.emit(RunEventType.NODE_FINISHED, "Report complete", node="report")
    # citations is an operator.add channel: only add ones not already in state
    update: dict = {"report": report.strip()}
    if not existing:
        update["citations"] = citations
    return update
