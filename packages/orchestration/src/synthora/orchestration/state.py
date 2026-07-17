"""LangGraph state schemas for the research OS (R-ODR-1).

Mirrors Open Deep Research's three-level design:
AgentState (top) -> SupervisorState (planning loop) -> ResearcherState (tool loop).
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Optional, TypedDict

from synthora.core.models import (
    Citation,
    DiscourseTurn,
    KnowledgeEdge,
    KnowledgeNode,
    OutlineNode,
    Perspective,
    SearchResult,
)


class AgentState(TypedDict, total=False):
    """Top-level pipeline state."""

    question: str
    clarification: Optional[str]
    pending_clarification: Optional[str]
    brief: str
    # research phase output
    notes: Annotated[list[str], operator.add]
    sources: Annotated[list[SearchResult], operator.add]
    citations: Annotated[list[Citation], operator.add]
    # intelligence phase (STORM) output
    perspectives: list[Perspective]
    discourse: list[DiscourseTurn]
    knowledge_nodes: list[KnowledgeNode]
    knowledge_edges: list[KnowledgeEdge]
    outline: Optional[OutlineNode]
    sections: Annotated[list[str], operator.add]
    critique: str
    # autonomous loop
    hypotheses: list[str]
    gaps: list[str]
    cycle: int
    # final output
    report: str
    metadata: dict[str, Any]


class SupervisorState(TypedDict, total=False):
    """State for the supervisor planning loop."""

    brief: str
    supervisor_messages: Annotated[list[dict], operator.add]
    research_iterations: int
    notes: Annotated[list[str], operator.add]
    sources: Annotated[list[SearchResult], operator.add]
    research_complete: bool


class ResearcherState(TypedDict, total=False):
    """State for one isolated researcher's ReAct loop."""

    topic: str
    tool_calls: int
    done: bool
    findings: Annotated[list[SearchResult], operator.add]
    researcher_notes: Annotated[list[str], operator.add]
    compressed: str


class ResearcherOutput(TypedDict, total=False):
    notes: list[str]
    sources: list[SearchResult]
