"""Co-STORM collaborative discourse (R-STORM-4).

Simulates a roundtable of expert personas plus a moderator:

- Experts take turns; each expert either answers with grounded, cited
  content or raises a question for the group.
- After ``experts_per_round`` consecutive expert turns, the moderator
  speaks: it surfaces *unused* retrieved evidence — snippets relevant to
  the topic but dissimilar to the current line of discussion — and turns
  it into a new question (Co-STORM's "unknown unknowns" move, with the
  ranking score sim(info, topic)^alpha * (1 - sim(info, discussion))^(1-alpha)).
"""

from __future__ import annotations

from typing import Optional

from synthora.core.models import Citation, DiscourseTurn, Perspective, SearchResult
from synthora.core.ports import ChatModel, SearchEngine
from synthora.intelligence.knowledge_map import SimilarityFn, jaccard


def rank_unused_evidence(
    unused: list[SearchResult],
    *,
    topic: str,
    discussion: str,
    alpha: float = 0.5,
    similarity: SimilarityFn = jaccard,
) -> list[tuple[SearchResult, float]]:
    """Rank unused snippets: topic-relevant but NOT already discussed."""
    scored = []
    for info in unused:
        text = f"{info.title} {info.snippet}"
        rel = similarity(text, topic)
        novelty = 1.0 - similarity(text, discussion)
        score = (rel**alpha) * (novelty ** (1.0 - alpha))
        scored.append((info, score))
    return sorted(scored, key=lambda pair: pair[1], reverse=True)


class DiscourseManager:
    def __init__(
        self,
        llm: ChatModel,
        *,
        engines: Optional[list[SearchEngine]] = None,
        experts_per_round: int = 2,
        alpha: float = 0.5,
        similarity: SimilarityFn = jaccard,
    ) -> None:
        self.llm = llm
        self.engines = engines or []
        self.experts_per_round = experts_per_round
        self.alpha = alpha
        self.similarity = similarity
        self.turns: list[DiscourseTurn] = []
        self.evidence_pool: list[SearchResult] = []
        self.used_urls: set[str] = set()

    # -- turn policy ---------------------------------------------------------

    def next_speaker(self, experts: list[Perspective]) -> str:
        """L consecutive expert turns, then the moderator."""
        if not self.turns:
            return experts[0].name
        recent_experts = 0
        for turn in reversed(self.turns):
            if turn.role == "expert":
                recent_experts += 1
            else:
                break
        if recent_experts >= self.experts_per_round:
            return "moderator"
        expert_turns = [t for t in self.turns if t.role == "expert"]
        return experts[len(expert_turns) % len(experts)].name

    # -- helpers ---------------------------------------------------------------

    def discussion_text(self, last_n: int = 8) -> str:
        return "\n".join(
            f"{t.speaker}: {t.utterance[:300]}" for t in self.turns[-last_n:]
        )

    def add_evidence(self, results: list[SearchResult]) -> None:
        known = {r.url.rstrip("/") for r in self.evidence_pool}
        for r in results:
            if r.url.rstrip("/") not in known:
                self.evidence_pool.append(r)
                known.add(r.url.rstrip("/"))

    def inject_user_turn(self, utterance: str) -> DiscourseTurn:
        """Human steering (R-STORM-6): the user joins the conversation."""
        turn = DiscourseTurn(
            speaker="user", role="user", utterance=utterance, intent="steer"
        )
        self.turns.append(turn)
        return turn

    async def warm_start(
        self, topic: str, perspectives: list[Perspective]
    ) -> list[str]:
        """Generate quick outline questions before discourse begins.

        Returns question strings (does not append turns); callers typically
        inject them via ``inject_user_turn``.
        """
        persona_block = "\n".join(
            f"- {p.name}: {p.focus or p.description}" for p in perspectives
        ) or "(no personas yet)"
        raw = await self.llm.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "You warm-start a research roundtable. Propose 3-5 short "
                        "outline questions that structure the upcoming discussion "
                        "across the listed expert angles. Return one question per "
                        "line, no numbering."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Topic: {topic}\n\nExpert angles:\n{persona_block}"
                    ),
                },
            ]
        )
        questions = [
            q.strip("-• ").strip()
            for q in raw.splitlines()
            if q.strip() and not q.strip().startswith("{")
        ]
        return questions[:5] or [f"What are the key open questions about {topic}?"]

    async def pure_rag_turn(self, topic: str) -> DiscourseTurn:
        """Answer from the evidence pool only — no expert persona (PureRAG)."""
        evidence = self.evidence_pool[:6]
        evidence_block = "\n".join(
            f"[{i + 1}] {r.title}: {(r.content or r.snippet)[:250]}"
            for i, r in enumerate(evidence)
        )
        raw = await self.llm.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a neutral PureRAG synthesizer (no expert persona). "
                        "Answer the topic using ONLY the evidence below. Cite claims "
                        "with [n] markers. If evidence is insufficient, say what is "
                        "missing. Prefix with 'ANSWER:'."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Topic: {topic}\n\nEvidence:\n{evidence_block or '(none)'}"
                    ),
                },
            ]
        )
        text = raw.strip()
        utterance = text.split(":", 1)[1].strip() if ":" in text[:12] else text
        citations = []
        for i, r in enumerate(evidence):
            marker = f"[{i + 1}]"
            if marker in utterance:
                citations.append(
                    Citation(url=r.url, title=r.title, snippet=r.snippet[:300])
                )
                self.used_urls.add(r.url.rstrip("/"))
        turn = DiscourseTurn(
            speaker="PureRAG",
            role="rag",
            utterance=utterance,
            intent="answer",
            citations=citations,
        )
        self.turns.append(turn)
        return turn

    async def simulated_user_turn(self, topic: str) -> DiscourseTurn:
        """LLM plays a curious user asking a follow-up (vs real ``inject_user_turn``)."""
        raw = await self.llm.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a curious learner in a research roundtable. Ask "
                        "ONE concrete follow-up question that probes a gap or "
                        "clarifies a claim from the discussion so far. Reply with "
                        "the question only."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Topic: {topic}\n\nDiscussion so far:\n"
                        f"{self.discussion_text() or '(just starting)'}"
                    ),
                },
            ]
        )
        turn = DiscourseTurn(
            speaker="user",
            role="user",
            utterance=raw.strip(),
            intent="question",
        )
        self.turns.append(turn)
        return turn

    # -- expert turn -----------------------------------------------------------

    async def expert_turn(
        self,
        expert: Perspective,
        topic: str,
        *,
        guided_questions: Optional[list[str]] = None,
    ) -> DiscourseTurn:
        questions = guided_questions or []
        query_hint = (
            questions[0]
            if questions
            else (self.turns[-1].utterance[:200] if self.turns else topic)
        )
        fresh: list[SearchResult] = []
        for engine in self.engines:
            try:
                fresh.extend(
                    await engine.search(f"{topic} {query_hint}"[:200], max_results=3)
                )
            except Exception:
                continue
        self.add_evidence(fresh)

        evidence = fresh[:4] or self.evidence_pool[:4]
        evidence_block = "\n".join(
            f"[{i + 1}] {r.title}: {(r.content or r.snippet)[:250]}"
            for i, r in enumerate(evidence)
        )
        guided_block = "\n".join(f"- {q}" for q in questions[:3])
        raw = await self.llm.complete(
            [
                {
                    "role": "system",
                    "content": (
                        f"You are {expert.name} ({expert.description}), focus: "
                        f"{expert.focus}. You are in a research roundtable. Based on "
                        "the discussion and evidence, either ANSWER with a grounded "
                        "insight citing [n] markers, or ASK one sharp question that "
                        "advances the discussion. Prefix your reply with 'ANSWER:' "
                        "or 'QUESTION:'."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Topic: {topic}\n\n"
                        f"Your prepared research questions:\n{guided_block or '(none)'}\n\n"
                        f"Discussion so far:\n"
                        f"{self.discussion_text() or '(opening turn)'}\n\n"
                        f"Evidence:\n{evidence_block or '(none)'}"
                    ),
                },
            ]
        )
        text = raw.strip()
        intent = "question" if text.upper().startswith("QUESTION") else "answer"
        utterance = text.split(":", 1)[1].strip() if ":" in text[:12] else text
        citations = []
        if intent == "answer":
            for i, r in enumerate(evidence):
                marker = f"[{i + 1}]"
                if marker in utterance:
                    citations.append(
                        Citation(url=r.url, title=r.title, snippet=r.snippet[:300])
                    )
                    self.used_urls.add(r.url.rstrip("/"))
        turn = DiscourseTurn(
            speaker=expert.name,
            role="expert",
            utterance=utterance,
            intent=intent,
            citations=citations,
        )
        self.turns.append(turn)
        return turn

    # -- moderator turn ----------------------------------------------------------

    def unused_evidence(self) -> list[SearchResult]:
        return [
            r for r in self.evidence_pool if r.url.rstrip("/") not in self.used_urls
        ]

    async def moderator_turn(self, topic: str) -> DiscourseTurn:
        unused = self.unused_evidence()
        ranked = rank_unused_evidence(
            unused,
            topic=topic,
            discussion=self.discussion_text(),
            alpha=self.alpha,
            similarity=self.similarity,
        )
        top = [r for r, _ in ranked[:3]]
        snippet_block = "\n".join(
            f"- {r.title}: {r.snippet[:200]}" for r in top
        )
        if top:
            raw = await self.llm.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "You moderate a research roundtable. These retrieved "
                            "snippets are relevant to the topic but have NOT been "
                            "discussed. Ask ONE question that steers the discussion "
                            "toward this unexplored ground. Reply with the question "
                            "only."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Topic: {topic}\n\nUnused evidence:\n{snippet_block}",
                    },
                ]
            )
            for r in top:
                self.used_urls.add(r.url.rstrip("/"))
        else:
            raw = await self.llm.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "You moderate a research roundtable. Ask ONE question "
                            "opening a genuinely new angle on the topic. Reply with "
                            "the question only."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Topic: {topic}\n\nDiscussion:\n{self.discussion_text()}",
                    },
                ]
            )
        turn = DiscourseTurn(
            speaker="moderator",
            role="moderator",
            utterance=raw.strip(),
            intent="question",
        )
        self.turns.append(turn)
        return turn

    # -- full discourse ------------------------------------------------------------

    async def run_discourse(
        self,
        topic: str,
        experts: list[Perspective],
        *,
        max_turns: int = 12,
        seed_evidence: Optional[list[SearchResult]] = None,
        guided_questions: Optional[dict[str, list[str]]] = None,
    ) -> list[DiscourseTurn]:
        if seed_evidence:
            self.add_evidence(seed_evidence)
        guided = guided_questions or {}
        expert_map = {e.name: e for e in experts}
        for _ in range(max_turns):
            speaker = self.next_speaker(experts)
            if speaker == "moderator":
                await self.moderator_turn(topic)
            else:
                await self.expert_turn(
                    expert_map[speaker],
                    topic,
                    guided_questions=guided.get(speaker, []),
                )
        return self.turns
