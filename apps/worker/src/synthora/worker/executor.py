"""Run executor: builds the research context, invokes the pipeline graph,
persists results, and streams progress (used by the worker process and by
integration tests)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from langgraph.types import Command
from synthora.adapters import llm_registry, search_engine_registry, strategy_registry
from synthora.core.events import ProgressEvent, RunEventType
from synthora.core.models import (
    Artifact,
    ArtifactKind,
    ResearchRun,
    RunStatus,
)
from synthora.orchestration import pipelines  # noqa: F401  (registers pipelines)
from synthora.orchestration.context import ResearchContext
from synthora.orchestration.registry import pipeline_registry
from synthora.persistence import (
    ArtifactRepository,
    CitationRepository,
    DiscourseRepository,
    EventRepository,
    KnowledgeRepository,
    MetricsRepository,
    ProviderSettingsRepository,
    RunRepositorySQL,
)
from synthora.persistence.database import Database
from synthora.worker.queue import RedisJobQueue

logger = logging.getLogger("synthora.worker")


class RunCancelled(Exception):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _has_interrupt(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    return bool(result.get("__interrupt__"))


def _interrupt_payload(result: dict) -> dict:
    interrupts = result.get("__interrupt__") or []
    if not interrupts:
        return {}
    first = interrupts[0]
    value = getattr(first, "value", first)
    if isinstance(value, dict):
        return value
    return {"question": str(value)}


class RunExecutor:
    def __init__(
        self,
        db: Database,
        queue: RedisJobQueue,
        *,
        model_resolver=None,
        engine_resolver=None,
        strategy_resolver=None,
    ) -> None:
        self.db = db
        self.queue = queue
        self._resolve_model = model_resolver or llm_registry.resolve
        self._resolve_engines = engine_resolver or search_engine_registry.resolve_many
        self._resolve_strategy = strategy_resolver or strategy_registry.resolve
        self.runs = RunRepositorySQL(db)
        self.events = EventRepository(db)
        self.artifacts = ArtifactRepository(db)
        self.citations = CitationRepository(db)
        self.knowledge = KnowledgeRepository(db)
        self.discourse = DiscourseRepository(db)
        self.metrics = MetricsRepository(db)

    def build_context(self, run: ResearchRun) -> ResearchContext:
        cfg = run.config

        async def sink(event: ProgressEvent) -> None:
            if await self.queue.is_cancelled(run.id):
                raise RunCancelled(run.id)
            for msg in await self.queue.drain_steering(run.id):
                ctx.steering.append(msg)
            await self.events.append(event)
            await self.queue.publish_event(run.id, event.to_wire())

        ctx = ResearchContext(
            run_id=run.id,
            config=cfg,
            planner=self._resolve_model(cfg.planner_model),
            researcher=self._resolve_model(cfg.researcher_model),
            compressor=self._resolve_model(cfg.compressor_model),
            writer=self._resolve_model(cfg.writer_model),
            critic=self._resolve_model(cfg.critic_model),
            engines=self._resolve_engines(cfg.search_engines),
            strategy=self._resolve_strategy(cfg.search_strategy),
            event_sink=sink,
        )
        ctx.wrap_providers()
        return ctx

    def _graph_config(self, run: ResearchRun, ctx: ResearchContext) -> dict:
        return {
            "configurable": {"synthora_ctx": ctx, "thread_id": run.id},
            "recursion_limit": 150,
        }

    async def _emit_status(self, run: ResearchRun, message: str = "") -> None:
        event = ProgressEvent(
            run_id=run.id,
            type=RunEventType.STATUS,
            message=message or run.status.value,
            payload={"status": run.status.value},
        )
        await self.events.append(event)
        await self.queue.publish_event(run.id, event.to_wire())

    async def execute(
        self,
        run_id: str,
        *,
        ctx: ResearchContext | None = None,
        resume_value: Optional[str] = None,
    ) -> ResearchRun:
        """Execute one research run to completion, interrupt, failure, or cancel.

        When ``resume_value`` is set, continues a previously interrupted run via
        LangGraph ``Command(resume=...)``.
        """
        from synthora.adapters.workspace_context import (
            reset_workspace_id,
            set_workspace_id,
        )

        run = await self.runs.get(run_id)
        if run is None:
            raise KeyError(f"run {run_id} not found")
        if await self.queue.is_cancelled(run.id):
            run.status = RunStatus.CANCELLED
            run.finished_at = utcnow()
            await self.runs.update(run)
            await self._emit_status(run)
            return run

        run.status = RunStatus.RUNNING
        if run.started_at is None:
            run.started_at = utcnow()
        run.finished_at = None
        run.error = None
        await self.runs.update(run)
        await self._emit_status(
            run, "Research resumed" if resume_value is not None else "Research started"
        )

        from synthora.adapters.provider_settings_context import (
            reset_provider_settings,
            set_provider_settings,
        )

        # Load workspace provider settings before resolving models/engines.
        try:
            rows = await ProviderSettingsRepository(self.db).list_settings(
                run.workspace_id or "default"
            )
            overlay = {r.key: dict(r.value or {}) for r in rows}
        except Exception:
            logger.exception(
                "failed to load provider settings for workspace %s",
                run.workspace_id,
            )
            overlay = {}

        settings_token = set_provider_settings(overlay)
        ws_token = set_workspace_id(run.workspace_id or "default")
        try:
            ctx = ctx or self.build_context(run)
            if not ctx.mcp_tools and (run.config.extra or {}).get("mcp"):
                from synthora.adapters.mcp_client import load_mcp_tools

                try:
                    ctx.mcp_tools = await load_mcp_tools(run.config.extra.get("mcp"))
                except Exception:
                    logger.exception("failed to load MCP tools for run %s", run.id)
                    ctx.mcp_tools = []
            graph = pipeline_registry.build(run.pipeline_id)
            config = self._graph_config(run, ctx)
            try:
                if resume_value is not None:
                    result = await graph.ainvoke(
                        Command(resume=resume_value), config=config
                    )
                else:
                    result = await graph.ainvoke(
                        {"question": run.question},
                        config=config,
                    )

                if _has_interrupt(result):
                    payload = _interrupt_payload(result)
                    await self.artifacts.save(
                        Artifact(
                            run_id=run.id,
                            kind=ArtifactKind.INTERRUPT_PAYLOAD,
                            content=json.dumps(payload),
                            metadata=payload,
                        )
                    )
                    run.status = RunStatus.AWAITING_INPUT
                    run.finished_at = None
                    await self.runs.update(run)
                    event = ProgressEvent(
                        run_id=run.id,
                        type=RunEventType.INTERRUPT,
                        message=str(payload.get("question", "")),
                        payload=payload,
                    )
                    await self.events.append(event)
                    await self.queue.publish_event(run.id, event.to_wire())
                    await self._emit_status(run, "Awaiting clarification")
                    try:
                        await self.metrics.save(ctx.to_metrics())
                    except Exception:
                        logger.exception(
                            "failed to persist metrics for run %s", run.id
                        )
                    return run

                await self._persist_result(run, result)
                run.brief = result.get("brief")
                run.status = RunStatus.COMPLETED
            except RunCancelled:
                run.status = RunStatus.CANCELLED
            except Exception as exc:
                logger.exception("run %s failed", run.id)
                run.error = f"{type(exc).__name__}: {exc}"
                run.status = RunStatus.FAILED
            try:
                await self.metrics.save(ctx.to_metrics())
            except Exception:
                logger.exception("failed to persist metrics for run %s", run.id)
            run.finished_at = utcnow()
            await self.runs.update(run)
            final_type = (
                RunEventType.DONE
                if run.status == RunStatus.COMPLETED
                else RunEventType.ERROR
            )
            event = ProgressEvent(
                run_id=run.id,
                type=final_type,
                message=run.error or run.status.value,
                payload={"status": run.status.value},
            )
            await self.events.append(event)
            await self.queue.publish_event(run.id, event.to_wire())
            return run
        finally:
            reset_workspace_id(ws_token)
            reset_provider_settings(settings_token)

    async def resume(self, run_id: str, answer: str) -> ResearchRun:
        """Resume a run paused at AWAITING_INPUT."""
        run = await self.runs.get(run_id)
        if run is None:
            raise KeyError(f"run {run_id} not found")
        if run.status != RunStatus.AWAITING_INPUT:
            raise ValueError(f"run is {run.status.value}, not awaiting_input")
        return await self.execute(run_id, resume_value=answer)

    async def _persist_result(self, run: ResearchRun, result: dict) -> None:
        report = result.get("report", "")
        if report:
            await self.artifacts.save(
                Artifact(
                    run_id=run.id,
                    kind=ArtifactKind.REPORT_MARKDOWN,
                    content=report,
                )
            )
        outline = result.get("outline")
        if outline is not None:
            from synthora.intelligence.outline import outline_to_markdown

            await self.artifacts.save(
                Artifact(
                    run_id=run.id,
                    kind=ArtifactKind.OUTLINE,
                    content=outline_to_markdown(outline),
                )
            )
        citations = result.get("citations") or []
        if citations:
            unique = list({c.id: c for c in citations}.values())
            for c in unique:
                c.run_id = run.id
            await self.citations.save_many(unique)
            url_map = {
                str(c.index): {"url": c.url, "title": c.title, "snippet": c.snippet}
                for c in unique
                if c.index is not None
            }
            await self.artifacts.save(
                Artifact(
                    run_id=run.id,
                    kind=ArtifactKind.URL_TO_INFO,
                    content=json.dumps(url_map),
                    metadata=url_map,
                )
            )
        nodes = result.get("knowledge_nodes") or []
        edges = result.get("knowledge_edges") or []
        if nodes:
            await self.knowledge.save_map(run.id, nodes, edges)
        notes = result.get("notes") or []
        if notes:
            await self.artifacts.save(
                Artifact(
                    run_id=run.id,
                    kind=ArtifactKind.RAW_NOTES,
                    content="\n\n".join(notes),
                )
            )
        discourse = result.get("discourse") or []
        if discourse:
            for turn in discourse:
                turn.run_id = run.id
            await self.discourse.save_many(discourse)
            log = "\n\n".join(
                f"**{t.speaker}** ({t.role}/{t.intent}): {t.utterance}"
                for t in discourse
            )
            await self.artifacts.save(
                Artifact(
                    run_id=run.id,
                    kind=ArtifactKind.DISCOURSE_LOG,
                    content=log,
                )
            )
