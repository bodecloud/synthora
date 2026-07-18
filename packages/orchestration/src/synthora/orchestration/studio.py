"""LangGraph Studio entry points (R-ODR-7).

`langgraph dev` imports compiled graphs from here. A default ResearchContext
is built from environment variables so graphs are runnable from Studio
without the platform layer.
"""

from __future__ import annotations

import os

from synthora.adapters import search_engine_registry, strategy_registry
from synthora.adapters.model_resolver import resolve_chat_model, resolve_run_config
from synthora.core.models import RunConfig
from synthora.orchestration import pipelines  # noqa: F401  (registers pipelines)
from synthora.orchestration.context import ResearchContext
from synthora.orchestration.registry import pipeline_registry


def default_context(run_id: str = "studio") -> ResearchContext:
    cfg = RunConfig(
        planner_model=os.environ.get("SYNTHORA_PLANNER_MODEL", "auto"),
        researcher_model=os.environ.get("SYNTHORA_RESEARCHER_MODEL", "auto"),
        compressor_model=os.environ.get("SYNTHORA_COMPRESSOR_MODEL", "auto"),
        writer_model=os.environ.get("SYNTHORA_WRITER_MODEL", "auto"),
        critic_model=os.environ.get("SYNTHORA_CRITIC_MODEL", "auto"),
        search_engines=os.environ.get("SYNTHORA_SEARCH_ENGINES", "searxng").split(","),
        search_strategy=os.environ.get("SYNTHORA_SEARCH_STRATEGY", "source_based"),
    )
    cfg = resolve_run_config(cfg)
    resolved_models: dict[str, str] = {}
    return ResearchContext(
        run_id=run_id,
        config=cfg,
        planner=resolve_chat_model(
            cfg.planner_model, role="planner", resolved_models=resolved_models
        ),
        researcher=resolve_chat_model(
            cfg.researcher_model, role="researcher", resolved_models=resolved_models
        ),
        compressor=resolve_chat_model(
            cfg.compressor_model, role="compressor", resolved_models=resolved_models
        ),
        writer=resolve_chat_model(
            cfg.writer_model, role="writer", resolved_models=resolved_models
        ),
        critic=resolve_chat_model(
            cfg.critic_model, role="critic", resolved_models=resolved_models
        ),
        engines=search_engine_registry.resolve_many(cfg.search_engines),
        strategy=strategy_registry.resolve(cfg.search_strategy),
        resolved_models=resolved_models,
    )


def _studio_graph(pipeline_id: str):
    graph = pipeline_registry.build(pipeline_id)
    return graph.with_config(
        {"configurable": {"synthora_ctx": default_context(pipeline_id)}}
    )


fast_research_graph = _studio_graph("fast_research")
deep_research_graph = _studio_graph("deep_research")
open_deep_research_graph = _studio_graph("open_deep_research")
academic_research_graph = _studio_graph("academic_research")
autonomous_research_graph = _studio_graph("autonomous_research")
