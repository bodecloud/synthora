"""Outline-first article generation (R-STORM-5).

STORM's write phase: draft an outline (optionally refined with discourse
transcripts and the knowledge map), then write each section grounded in
collected sources with [n] citations, then polish.
"""

from __future__ import annotations

from typing import Optional

from synthora.core.models import Citation, OutlineNode
from synthora.core.parsing import parse_json_response
from synthora.core.ports import ChatModel, EmbeddingModel
from synthora.intelligence.embeddings import cosine_similarity
from synthora.intelligence.knowledge_map import KnowledgeMap, SimilarityFn, jaccard


def _outline_from_json(data) -> Optional[OutlineNode]:
    if not isinstance(data, dict) or not data.get("title"):
        return None
    return OutlineNode(
        title=str(data["title"]),
        children=[
            child
            for c in data.get("children", [])
            if (child := _outline_from_json(c)) is not None
        ],
    )


def outline_to_markdown(node: OutlineNode, depth: int = 1) -> str:
    lines = [f"{'#' * min(depth, 6)} {node.title}"]
    for child in node.children:
        lines.append(outline_to_markdown(child, depth + 1))
    return "\n".join(lines)


def flatten_sections(node: OutlineNode) -> list[OutlineNode]:
    """Top-level sections to write (children of the root)."""
    return node.children or [node]


class OutlineBuilder:
    def __init__(self, llm: ChatModel) -> None:
        self.llm = llm

    async def build(
        self,
        brief: str,
        *,
        notes: str = "",
        discourse_transcript: str = "",
        knowledge_map: Optional[KnowledgeMap] = None,
    ) -> OutlineNode:
        context_parts = []
        if knowledge_map is not None:
            context_parts.append(
                f"Knowledge map:\n{knowledge_map.to_outline_text()}"
            )
        if discourse_transcript:
            context_parts.append(
                f"Expert discussion transcript:\n{discourse_transcript[:4000]}"
            )
        if notes:
            context_parts.append(f"Research notes:\n{notes[:6000]}")
        raw = await self.llm.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "Design a report outline for the research brief. Ground it "
                        "in the provided context — cover discovered subtopics, not "
                        "generic boilerplate.\n"
                        'Reply JSON: {"title": "...", "children": [{"title": "...", '
                        '"children": [...]}]} with 4-7 top-level sections.'
                    ),
                },
                {
                    "role": "user",
                    "content": brief + "\n\n" + "\n\n".join(context_parts),
                },
            ]
        )
        outline = _outline_from_json(parse_json_response(raw))
        if outline is None:
            outline = OutlineNode(
                title=brief[:80],
                children=[
                    OutlineNode(title="Background"),
                    OutlineNode(title="Key findings"),
                    OutlineNode(title="Analysis"),
                    OutlineNode(title="Conclusion"),
                ],
            )
        if knowledge_map is not None:
            self._link_knowledge(outline, knowledge_map)
        return outline

    def _link_knowledge(self, outline: OutlineNode, kmap: KnowledgeMap) -> None:
        """Attach the most similar knowledge nodes to each section."""
        for section in flatten_sections(outline):
            scored = sorted(
                kmap.nodes.values(),
                key=lambda n: jaccard(section.title, f"{n.name} {n.summary}"),
                reverse=True,
            )
            section.knowledge_node_ids = [n.id for n in scored[:3]]


class SectionWriter:
    def __init__(
        self,
        llm: ChatModel,
        *,
        embeddings: Optional[EmbeddingModel] = None,
        similarity: SimilarityFn = jaccard,
    ) -> None:
        self.llm = llm
        self.embeddings = embeddings
        self.similarity = similarity

    async def _rank_citations(
        self, section_title: str, citations: list[Citation]
    ) -> list[Citation]:
        """Prefer embedding cosine when an embedder is available; else lexical."""
        if self.embeddings is not None and citations:
            texts = [section_title] + [
                f"{c.title} {c.snippet}" for c in citations
            ]
            try:
                vectors = await self.embeddings.embed(texts)
            except Exception:
                vectors = []
            if len(vectors) == len(texts):
                query_vec = vectors[0]
                scored = [
                    (citations[i], cosine_similarity(query_vec, vectors[i + 1]))
                    for i in range(len(citations))
                ]
                scored.sort(key=lambda pair: pair[1], reverse=True)
                return [c for c, _ in scored][:12]
        return sorted(
            citations,
            key=lambda c: self.similarity(
                section_title, f"{c.title} {c.snippet}"
            ),
            reverse=True,
        )[:12]

    async def write_section(
        self,
        section: OutlineNode,
        *,
        brief: str,
        citations: list[Citation],
        notes: str = "",
    ) -> str:
        """Write one section with [n] citation markers (semantic retrieval:
        the most relevant citations for this section title are offered)."""
        relevant = await self._rank_citations(section.title, citations)
        sources_block = "\n".join(
            f"[{c.index}] {c.title}: {c.snippet[:200]}" for c in relevant if c.index
        )
        subsections = ", ".join(c.title for c in section.children) or "none"
        text = await self.llm.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "Write one section of a research report in Markdown. Start "
                        "with the section heading (##). Cite every factual claim "
                        "with [n] markers from the source list. Be dense and "
                        "specific; no filler."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Report brief: {brief}\nSection: {section.title}\n"
                        f"Planned subsections: {subsections}\n\n"
                        f"Sources:\n{sources_block or '(none)'}\n\n"
                        f"Relevant notes:\n{notes[:5000]}"
                    ),
                },
            ],
            temperature=0.4,
        )
        return text.strip()

    async def polish(self, draft: str, *, brief: str) -> str:
        """Dedup + lead summary (STORM's polish stage)."""
        return (
            await self.llm.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "Polish this research report: add a one-paragraph "
                            "executive summary at the top, remove duplicated "
                            "content across sections, keep all [n] citation "
                            "markers intact. Return the full polished Markdown."
                        ),
                    },
                    {"role": "user", "content": f"Brief: {brief}\n\n{draft}"},
                ],
                temperature=0.3,
            )
        ).strip()
