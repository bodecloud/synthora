"""Shared MCP tool catalog and execution (REST + streamable HTTP)."""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import HTTPException
from mcp.server.fastmcp import Context
from starlette.requests import Request
from synthora.api.auth import identity_from_token
from synthora.api.settings import settings
from synthora.core.models import ArtifactKind, ResearchRun, RunConfig
from synthora.orchestration.registry import pipeline_registry
from synthora.persistence import (
    ArtifactRepository,
    DocumentRepository,
    RunRepositorySQL,
)
from synthora.persistence.database import Database
from synthora.worker.queue import RedisJobQueue


class McpToolError(Exception):
    """Tool execution failure surfaced to REST (HTTP) or MCP clients (text)."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


MCP_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "start_research",
        "description": "Start a research run. Args: question, pipeline_id optional.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "pipeline_id": {"type": "string"},
                "config": {
                    "type": "object",
                    "description": "Optional RunConfig fields (engines, models, limits, extra)",
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "get_run_status",
        "description": "Get status for a research run. Args: run_id.",
        "inputSchema": {
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
        },
    },
    {
        "name": "get_report",
        "description": "Fetch the markdown report for a completed run. Args: run_id.",
        "inputSchema": {
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
        },
    },
    {
        "name": "search_documents",
        "description": (
            "Search the workspace document library. Args: query, max_results."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
]


def identity_from_context(ctx: Context) -> dict:
    """Resolve workspace identity from the streamable HTTP Authorization header."""
    request: Optional[Request] = ctx.request_context.request
    token: Optional[str] = None
    if request is not None:
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            token = header.removeprefix("Bearer ").strip()
    try:
        return identity_from_token(token)
    except HTTPException as exc:
        raise McpToolError(str(exc.detail), status=exc.status_code) from exc


async def _get_run_checked(
    run_id: str, identity: dict, db: Database
) -> ResearchRun:
    run = await RunRepositorySQL(db).get(run_id)
    if run is None:
        raise McpToolError("run not found", status=404)
    if settings.auth_mode == "session" and run.workspace_id != identity["workspace_id"]:
        raise McpToolError("run not found", status=404)
    return run


def _embedding_model():
    from synthora.adapters.embeddings import resolve_default_embeddings

    return resolve_default_embeddings()


async def execute_mcp_tool(
    name: str,
    args: dict[str, Any],
    *,
    identity: dict,
    db: Database,
    queue: RedisJobQueue,
) -> dict[str, str]:
    """Run one MCP tool and return ``{"content": ...}``."""
    if name == "start_research":
        question = str(args.get("question") or "").strip()
        if len(question) < 3:
            raise McpToolError("question required", status=422)
        pipeline_id = str(args.get("pipeline_id") or "fast_research")
        try:
            pipeline_registry.get(pipeline_id)
        except KeyError as exc:
            raise McpToolError(str(exc), status=422) from exc
        config = RunConfig.model_validate(
            {**(args.get("config") or {}), "pipeline_id": pipeline_id}
        )
        run = ResearchRun(
            question=question,
            pipeline_id=pipeline_id,
            workspace_id=identity["workspace_id"],
            config=config,
        )
        await RunRepositorySQL(db).create(run)
        await queue.enqueue(run.id, {"pipeline_id": run.pipeline_id})
        return {
            "content": json.dumps({"run_id": run.id, "status": run.status.value})
        }

    if name == "get_run_status":
        run_id = str(args.get("run_id") or "")
        run = await _get_run_checked(run_id, identity, db)
        return {
            "content": json.dumps(
                {"run_id": run.id, "status": run.status.value, "error": run.error}
            )
        }

    if name == "get_report":
        run_id = str(args.get("run_id") or "")
        await _get_run_checked(run_id, identity, db)
        artifacts = await ArtifactRepository(db).list_for_run(run_id)
        report = next(
            (a for a in artifacts if a.kind == ArtifactKind.REPORT_MARKDOWN), None
        )
        if report is None:
            raise McpToolError("report not ready", status=404)
        return {"content": report.content}

    if name == "search_documents":
        query = str(args.get("query") or "")
        max_results = int(args.get("max_results") or 5)
        embedder = _embedding_model()
        query_vec = (await embedder.embed([query]))[0] if query else []
        hits = await DocumentRepository(db).search(
            identity["workspace_id"],
            query=query,
            query_embedding=query_vec or None,
            max_results=max_results,
        )
        return {"content": json.dumps({"results": hits})}

    raise McpToolError(f"unknown tool: {name}", status=404)
