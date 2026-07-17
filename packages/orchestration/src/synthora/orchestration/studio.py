"""LangGraph Studio entry points (R-ODR-7).

`langgraph dev` imports compiled graphs from here. A default ResearchContext
is built from environment variables so graphs are runnable from Studio
without the platform layer.
"""

from __future__ import annotations

import os

from synthora.adapters import llm_registry, search_engine_registry, strategy_registry
from synthora.core.models import RunConfig
from synthora.orchestration import pipelines  # noqa: F401  (registers pipelines)
from synthora.orchestration.context import ResearchContext
from synthora.orchestration.registry import pipeline_registry


def default_context(run_id: str = "studio") -> ResearchContext:
    cfg = RunConfig(
        planner_model=os.environ.get("SYNTHORA_PLANNER_MODEL", "openai:gpt-4o-mini"),
        researcher_model=os.environ.get("SYNTHORA_RESEARCHER_MODEL", "openai:gpt-4o-mini"),
        compressor_model=os.environ.get("SYNTHORA_COMPRESSOR_MODEL", "openai:gpt-4o-mini"),
        writer_model=os.environ.get("SYNTHORA_WRITER_MODEL", "openai:gpt-4o"),
        critic_model=os.environ.get("SYNTHORA_CRITIC_MODEL", "openai:gpt-4o-mini"),
        search_engines=os.environ.get("SYNTHORA_SEARCH_ENGINES", "searxng").split(","),
        search_strategy=os.environ.get("SYNTHORA_SEARCH_STRATEGY", "source_based"),
    )
    return ResearchContext(
        run_id=run_id,
        config=cfg,
        planner=llm_registry.resolve(cfg.planner_model),
        researcher=llm_registry.resolve(cfg.researcher_model),
        compressor=llm_registry.resolve(cfg.compressor_model),
        writer=llm_registry.resolve(cfg.writer_model),
        critic=llm_registry.resolve(cfg.critic_model),
        engines=search_engine_registry.resolve_many(cfg.search_engines),
        strategy=strategy_registry.resolve(cfg.search_strategy),
    )


def _studio_graph(pipeline_id: str):
    graph = pipeline_registry.build(pipeline_id)
    return graph.with_config(
        {"configurable": {"synthora_ctx": default_context(pipeline_id)}}
    )


fast_research_graph = _studio_graph("fast_research")
deep_research_graph = _studio_graph("deep_research")
academic_research_graph = _studio_graph("academic_research")
autonomous_research_graph = _studio_graph("autonomous_research")
