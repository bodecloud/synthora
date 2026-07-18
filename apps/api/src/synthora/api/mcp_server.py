"""Streamable HTTP MCP server exposing Synthora research tools."""

from __future__ import annotations

import json

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from synthora.api.mcp_runtime import get_mcp_runtime
from synthora.api.mcp_tools import McpToolError, execute_mcp_tool, identity_from_context

synthora_mcp = FastMCP(
    "Synthora",
    instructions=(
        "Synthora deep-research platform. Start runs, poll status, fetch reports, "
        "and search the workspace document library."
    ),
    streamable_http_path="/",
    json_response=True,
    stateless_http=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)


def _json_error(exc: McpToolError) -> str:
    return json.dumps({"error": exc.message, "status": exc.status})


@synthora_mcp.tool()
async def start_research(
    question: str,
    pipeline_id: str = "fast_research",
    ctx: Context = None,  # type: ignore[assignment]
) -> str:
    """Start a research run for a natural-language question."""
    db, queue = get_mcp_runtime()
    try:
        result = await execute_mcp_tool(
            "start_research",
            {"question": question, "pipeline_id": pipeline_id},
            identity=identity_from_context(ctx),
            db=db,
            queue=queue,
        )
    except McpToolError as exc:
        return _json_error(exc)
    return result["content"]


@synthora_mcp.tool()
async def get_run_status(
    run_id: str,
    ctx: Context = None,  # type: ignore[assignment]
) -> str:
    """Return the lifecycle status for a research run."""
    db, queue = get_mcp_runtime()
    try:
        result = await execute_mcp_tool(
            "get_run_status",
            {"run_id": run_id},
            identity=identity_from_context(ctx),
            db=db,
            queue=queue,
        )
    except McpToolError as exc:
        return _json_error(exc)
    return result["content"]


@synthora_mcp.tool()
async def get_report(
    run_id: str,
    ctx: Context = None,  # type: ignore[assignment]
) -> str:
    """Fetch the markdown report for a completed run."""
    db, queue = get_mcp_runtime()
    try:
        result = await execute_mcp_tool(
            "get_report",
            {"run_id": run_id},
            identity=identity_from_context(ctx),
            db=db,
            queue=queue,
        )
    except McpToolError as exc:
        return _json_error(exc)
    return result["content"]


@synthora_mcp.tool()
async def search_documents(
    query: str,
    max_results: int = 5,
    ctx: Context = None,  # type: ignore[assignment]
) -> str:
    """Search the workspace document library (RAG collection)."""
    db, queue = get_mcp_runtime()
    try:
        result = await execute_mcp_tool(
            "search_documents",
            {"query": query, "max_results": max_results},
            identity=identity_from_context(ctx),
            db=db,
            queue=queue,
        )
    except McpToolError as exc:
        return _json_error(exc)
    return result["content"]


def mcp_streamable_app():
    """ASGI app mounted at ``/mcp`` (endpoint path is ``/`` inside the mount)."""
    return synthora_mcp.streamable_http_app()


def refresh_mcp_streamable_mount(fastapi_app) -> None:
    """Use a new session manager when API lifespan restarts (e.g. tests)."""
    manager = synthora_mcp._session_manager
    if manager is not None and manager._has_started:
        synthora_mcp._session_manager = None
        new_asgi = synthora_mcp.streamable_http_app()
        from starlette.routing import Mount

        for route in fastapi_app.routes:
            if isinstance(route, Mount) and route.path.rstrip("/") == "/mcp":
                route.app = new_asgi
                return
        fastapi_app.mount("/mcp", new_asgi)
