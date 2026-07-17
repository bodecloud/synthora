"""Search strategies (R-LDR-4): how queries are generated and results merged.

Ported concepts from Local Deep Research's strategy layer:

- ``source_based``: decompose the topic into sub-queries, fan out across
  engines, deduplicate by URL, rank by score.
- ``focused_iteration``: iterate query refinement — search, ask the LLM
  what is still missing, search again with a refined query.
- ``focused_iteration_standard``: same loop, but keeps longer snippets for
  citation quality.
- ``topic_organization``: collect sources then cluster into topics with
  lead texts via the LLM.
- ``langgraph_agent``: LLM selects engines per sub-question, parallel
  fan-out, up to N iterations.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Callable

from synthora.core.models import SearchResult
from synthora.core.ports import ChatModel, SearchEngine

StrategyFactory = Callable[[], "object"]


def dedupe_results(results: list[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    unique: list[SearchResult] = []
    for r in sorted(results, key=lambda r: r.score, reverse=True):
        key = r.url.rstrip("/")
        if key and key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


async def _fan_out(
    queries: list[str], engines: list[SearchEngine], per_query: int
) -> list[SearchResult]:
    tasks = [
        engine.search(q, max_results=per_query) for q in queries for engine in engines
    ]
    batches = await asyncio.gather(*tasks, return_exceptions=True)
    results: list[SearchResult] = []
    for batch in batches:
        if isinstance(batch, BaseException):
            continue  # one engine failing must not sink the strategy
        results.extend(batch)
    return results


def _elongate_snippets(results: list[SearchResult], length: int = 800) -> list[SearchResult]:
    """Ensure snippet fields carry enough text for citation."""
    elongated: list[SearchResult] = []
    for r in results:
        source = r.content or r.snippet or ""
        snippet = (source[:length] if source else r.snippet) or ""
        elongated.append(r.model_copy(update={"snippet": snippet}))
    return elongated


class SourceBasedStrategy:
    """Decompose into sub-queries, fan out, dedupe, rank."""

    name = "source_based"

    async def run(
        self,
        topic: str,
        *,
        engines: list[SearchEngine],
        llm: ChatModel,
        max_results: int = 8,
    ) -> list[SearchResult]:
        raw = await llm.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "Decompose the research topic into 3 focused web search "
                        "queries. Return one query per line, no numbering."
                    ),
                },
                {"role": "user", "content": topic},
            ]
        )
        queries = [q.strip("-• ").strip() for q in raw.splitlines() if q.strip()][:3]
        if not queries:
            queries = [topic]
        results = await _fan_out(queries, engines, per_query=max(2, max_results // 2))
        return dedupe_results(results)[:max_results]


class FocusedIterationStrategy:
    """Search, reflect on gaps, refine the query, search again."""

    name = "focused_iteration"
    snippet_len = 150

    def __init__(self, iterations: int = 2) -> None:
        self.iterations = iterations

    async def run(
        self,
        topic: str,
        *,
        engines: list[SearchEngine],
        llm: ChatModel,
        max_results: int = 8,
    ) -> list[SearchResult]:
        collected: list[SearchResult] = []
        query = topic
        for _ in range(max(1, self.iterations)):
            batch = await _fan_out([query], engines, per_query=max_results)
            collected.extend(batch)
            summary = "\n".join(
                f"- {r.title}: {r.snippet[: self.snippet_len]}"
                for r in dedupe_results(collected)[:8]
            )
            query = (
                await llm.complete(
                    [
                        {
                            "role": "system",
                            "content": (
                                "Given a research topic and findings so far, produce "
                                "ONE refined search query targeting the biggest "
                                "remaining information gap. Reply with the query only."
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"Topic: {topic}\nFindings:\n{summary}",
                        },
                    ]
                )
            ).strip()
            if not query:
                break
        return dedupe_results(collected)[:max_results]


class FocusedIterationStandardStrategy(FocusedIterationStrategy):
    """Focused iteration that keeps longer snippets for citation quality."""

    name = "focused_iteration_standard"
    snippet_len = 500

    async def run(
        self,
        topic: str,
        *,
        engines: list[SearchEngine],
        llm: ChatModel,
        max_results: int = 8,
    ) -> list[SearchResult]:
        results = await super().run(
            topic, engines=engines, llm=llm, max_results=max_results
        )
        return _elongate_snippets(results, length=800)


class TopicOrganizationStrategy:
    """Fan out like source-based, then cluster sources into topics via LLM."""

    name = "topic_organization"

    async def run(
        self,
        topic: str,
        *,
        engines: list[SearchEngine],
        llm: ChatModel,
        max_results: int = 8,
    ) -> list[SearchResult]:
        # First gather a broad pool of sources.
        gatherer = SourceBasedStrategy()
        pool = await gatherer.run(
            topic, engines=engines, llm=llm, max_results=max(max_results * 2, 12)
        )
        if not pool:
            return []

        catalog = "\n".join(
            f"[{i}] {r.title}: {r.snippet[:200]}" for i, r in enumerate(pool)
        )
        raw = await llm.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "Cluster the numbered sources into 2-5 topics. For each "
                        "topic reply with a JSON object on its own line: "
                        '{"topic":"...","lead":"...","indices":[0,1]}. '
                        "No markdown fences."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Research topic: {topic}\nSources:\n{catalog}",
                },
            ]
        )
        clusters = _parse_topic_clusters(raw)
        annotated: list[SearchResult] = []
        used: set[int] = set()
        for cluster in clusters:
            lead = cluster.get("lead") or cluster.get("topic") or ""
            topic_name = cluster.get("topic") or "topic"
            for idx in cluster.get("indices") or []:
                if not isinstance(idx, int) or idx < 0 or idx >= len(pool):
                    continue
                if idx in used:
                    continue
                used.add(idx)
                src = pool[idx]
                annotated.append(
                    src.model_copy(
                        update={
                            "metadata": {
                                **src.metadata,
                                "topic": topic_name,
                                "lead": lead,
                            }
                        }
                    )
                )
        # Append any unclustered sources without topic metadata.
        for i, src in enumerate(pool):
            if i not in used:
                annotated.append(src)
        return dedupe_results(annotated)[:max_results]


def _parse_topic_clusters(raw: str) -> list[dict]:
    clusters: list[dict] = []
    for line in (raw or "").splitlines():
        line = line.strip().strip(",")
        if not line or not line.startswith("{"):
            # try to extract a JSON object substring
            match = re.search(r"\{.*\}", line)
            if not match:
                continue
            line = match.group(0)
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            clusters.append(obj)
    if clusters:
        return clusters
    # Fallback: whole blob as a JSON array
    try:
        blob = json.loads(raw)
        if isinstance(blob, list):
            return [c for c in blob if isinstance(c, dict)]
    except json.JSONDecodeError:
        pass
    return []


class LangGraphAgentStrategy:
    """LLM picks engines per sub-question, parallel fan-out, up to N iterations."""

    name = "langgraph_agent"

    def __init__(self, iterations: int = 2) -> None:
        self.iterations = iterations

    async def run(
        self,
        topic: str,
        *,
        engines: list[SearchEngine],
        llm: ChatModel,
        max_results: int = 8,
    ) -> list[SearchResult]:
        engine_names = [e.name for e in engines]
        engines_by_name = {e.name: e for e in engines}
        collected: list[SearchResult] = []

        for iteration in range(max(1, self.iterations)):
            findings = "\n".join(
                f"- {r.title}: {r.snippet[:120]}"
                for r in dedupe_results(collected)[:8]
            ) or "(none yet)"
            raw = await llm.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "You are a research agent. Given a topic, available "
                            "search engines, and findings so far, propose up to 3 "
                            "sub-questions. For each, pick one engine. Reply with "
                            'JSON lines: {"query":"...","engine":"..."}. '
                            f"Available engines: {', '.join(engine_names)}. "
                            "No markdown."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Topic: {topic}\nIteration: {iteration + 1}\n"
                            f"Findings:\n{findings}"
                        ),
                    },
                ]
            )
            plans = _parse_agent_plans(raw, engine_names)
            if not plans:
                # Fallback: search topic on all engines once.
                if iteration == 0:
                    collected.extend(
                        await _fan_out([topic], engines, per_query=max_results)
                    )
                break

            tasks = []
            for plan in plans:
                eng = engines_by_name.get(plan["engine"])
                if eng is None:
                    continue
                tasks.append(eng.search(plan["query"], max_results=max_results))
            if not tasks:
                break
            batches = await asyncio.gather(*tasks, return_exceptions=True)
            for batch in batches:
                if isinstance(batch, BaseException):
                    continue
                collected.extend(batch)

        return dedupe_results(collected)[:max_results]


def _parse_agent_plans(raw: str, engine_names: list[str]) -> list[dict[str, str]]:
    plans: list[dict[str, str]] = []
    default_engine = engine_names[0] if engine_names else ""
    for line in (raw or "").splitlines():
        line = line.strip().strip(",")
        match = re.search(r"\{.*\}", line)
        if not match:
            # plain "query | engine" fallback
            if "|" in line and line:
                q, _, eng = line.partition("|")
                eng = eng.strip()
                if eng not in engine_names:
                    eng = default_engine
                if q.strip() and eng:
                    plans.append({"query": q.strip(), "engine": eng})
            continue
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        query = str(obj.get("query") or obj.get("q") or "").strip()
        engine = str(obj.get("engine") or "").strip()
        if engine not in engine_names:
            engine = default_engine
        if query and engine:
            plans.append({"query": query, "engine": engine})
    return plans[:3]


class SearchStrategyRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, StrategyFactory] = {}

    def register(self, name: str, factory: StrategyFactory) -> None:
        self._factories[name] = factory

    def strategies(self) -> list[str]:
        return sorted(self._factories)

    def resolve(self, name: str):
        if name not in self._factories:
            raise KeyError(
                f"unknown search strategy '{name}' (known: {self.strategies()})"
            )
        return self._factories[name]()


strategy_registry = SearchStrategyRegistry()
strategy_registry.register("source_based", SourceBasedStrategy)
strategy_registry.register("source-based", SourceBasedStrategy)
strategy_registry.register("focused_iteration", FocusedIterationStrategy)
strategy_registry.register("focused-iteration", FocusedIterationStrategy)
strategy_registry.register(
    "focused_iteration_standard", FocusedIterationStandardStrategy
)
strategy_registry.register("topic_organization", TopicOrganizationStrategy)
strategy_registry.register("topic", TopicOrganizationStrategy)
strategy_registry.register("langgraph_agent", LangGraphAgentStrategy)
strategy_registry.register("langgraph-agent", LangGraphAgentStrategy)
