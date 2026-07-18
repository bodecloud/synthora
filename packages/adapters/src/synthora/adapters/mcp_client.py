"""MCP client bridge: load tools from servers listed in RunConfig.extra["mcp"].

Preferred path uses ``langchain-mcp-adapters``. If that import or connection
fails, a minimal HTTP JSON-RPC fallback talks to MCP-ish ``tools/list`` /
``tools/call`` endpoints (including Synthora's own REST MCP surface).

Remote MCP URLs are gated by ``SYNTHORA_MCP_ALLOWLIST`` (comma-separated hosts)
to prevent SSRF from run configs. Localhost is always allowed for local dev.
"""

from __future__ import annotations

import ipaddress
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("synthora.adapters.mcp")

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def validate_mcp_url(url: str) -> str:
    """Reject unsafe MCP URLs (SSRF guard). Returns the normalized URL."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("MCP URL must use http or https")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("MCP URL missing host")

    allowlist = {
        h.strip().lower()
        for h in os.environ.get("SYNTHORA_MCP_ALLOWLIST", "").split(",")
        if h.strip()
    }
    if host in _LOCAL_HOSTS or host in allowlist:
        return url.rstrip("/")

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    ):
        raise ValueError(f"MCP URL blocked (private/reserved host): {host}")

    if not allowlist:
        raise ValueError(
            "Remote MCP hosts require SYNTHORA_MCP_ALLOWLIST "
            f"(got {host!r})"
        )
    raise ValueError(f"MCP host {host!r} not in SYNTHORA_MCP_ALLOWLIST")


@dataclass
class MCPTool:
    """Callable tool handle returned to the researcher ReAct loop."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    _server_url: str = ""
    _transport: str = "http"
    _callable: Any = None
    _headers: dict[str, str] = field(default_factory=dict)

    async def ainvoke(self, arguments: Optional[dict[str, Any]] = None) -> str:
        args = arguments or {}
        if self._callable is not None:
            result = self._callable(args)
            if hasattr(result, "__await__"):
                result = await result
            return str(result)
        return await _http_tools_call(
            self._server_url, self.name, args, headers=self._headers
        )


def _auth_headers(mcp_config: dict[str, Any], server: dict[str, Any]) -> dict[str, str]:
    """Build Authorization headers for Synthora session-auth MCP self-calls."""
    headers: dict[str, str] = {}
    token = (
        server.get("token")
        or server.get("auth_token")
        or mcp_config.get("token")
        or os.environ.get("SYNTHORA_INTERNAL_TOKEN")
        or os.environ.get("SYNTHORA_API_TOKEN")
        or ""
    )
    if token:
        headers["Authorization"] = f"Bearer {token}"
    extra = server.get("headers") or mcp_config.get("headers") or {}
    if isinstance(extra, dict):
        for key, value in extra.items():
            headers[str(key)] = str(value)
    return headers


async def load_mcp_tools(mcp_config: Optional[dict[str, Any]]) -> list[MCPTool]:
    """Load tools from ``{"servers": [{"url": "...", "transport": "http"}]}``."""
    if not mcp_config:
        return []
    servers = mcp_config.get("servers") or []
    if not isinstance(servers, list) or not servers:
        return []

    # Prefer langchain-mcp-adapters when available.
    try:
        tools = await _load_via_langchain(mcp_config, servers)
        if tools:
            return tools
    except Exception as exc:  # noqa: BLE001 — fall back to HTTP list/call
        logger.debug("langchain-mcp-adapters unavailable: %s", exc)

    tools: list[MCPTool] = []
    failures: list[str] = []
    for server in servers:
        if not isinstance(server, dict):
            continue
        raw_url = str(server.get("url") or "").rstrip("/")
        transport = str(server.get("transport") or "http")
        if not raw_url:
            continue
        try:
            url = validate_mcp_url(raw_url)
        except ValueError as exc:
            failures.append(str(exc))
            logger.warning("MCP URL rejected: %s", exc)
            continue
        headers = _auth_headers(mcp_config, server)
        try:
            listed = await _http_tools_list(url, headers=headers)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{url}: {exc}")
            logger.warning("MCP list failed for %s: %s", url, exc)
            continue
        for item in listed:
            name = str(item.get("name") or "")
            if not name:
                continue
            tools.append(
                MCPTool(
                    name=name,
                    description=str(item.get("description") or ""),
                    input_schema=dict(
                        item.get("inputSchema") or item.get("input_schema") or {}
                    ),
                    _server_url=url,
                    _transport=transport,
                    _headers=headers,
                )
            )
    if not tools and failures:
        raise RuntimeError(
            "MCP tool loading failed for all servers: " + "; ".join(failures)
        )
    return tools


async def _load_via_langchain(
    mcp_config: dict[str, Any], servers: list[dict]
) -> list[MCPTool]:
    from langchain_mcp_adapters.client import MultiServerMCPClient  # type: ignore

    connections: dict[str, dict[str, Any]] = {}
    for i, server in enumerate(servers):
        if not isinstance(server, dict):
            continue
        raw_url = str(server.get("url") or "").rstrip("/")
        if not raw_url:
            continue
        try:
            url = validate_mcp_url(raw_url)
        except ValueError as exc:
            logger.warning("MCP URL rejected: %s", exc)
            continue
        transport = str(server.get("transport") or "sse")
        key = str(server.get("name") or f"server_{i}")
        headers = _auth_headers(mcp_config, server)
        conn: dict[str, Any]
        if transport in ("http", "streamable_http", "streamable-http"):
            conn = {"url": url, "transport": "streamable_http"}
        else:
            conn = {"url": url, "transport": transport or "sse"}
        if headers:
            conn["headers"] = headers
        connections[key] = conn
    if not connections:
        return []
    client = MultiServerMCPClient(connections)
    lc_tools = await client.get_tools()
    out: list[MCPTool] = []
    for tool in lc_tools:
        name = getattr(tool, "name", "") or ""
        desc = getattr(tool, "description", "") or ""
        schema = getattr(tool, "args_schema", None)
        input_schema: dict[str, Any] = {}
        if schema is not None and hasattr(schema, "model_json_schema"):
            input_schema = schema.model_json_schema()
        out.append(
            MCPTool(
                name=name,
                description=desc,
                input_schema=input_schema,
                _callable=getattr(tool, "ainvoke", None) or getattr(tool, "invoke", None),
            )
        )
    return out


async def _http_tools_list(
    base_url: str, *, headers: Optional[dict[str, str]] = None
) -> list[dict[str, Any]]:
    """Call Synthora-style REST or JSON-RPC tools/list."""
    hdrs = dict(headers or {})
    async with httpx.AsyncClient(timeout=20.0) as client:
        # Synthora REST surface
        resp = await client.post(
            f"{base_url}/api/v1/mcp/tools/list", json={}, headers=hdrs
        )
        if resp.status_code < 400:
            data = resp.json()
            tools = data.get("tools") if isinstance(data, dict) else None
            if isinstance(tools, list):
                return tools
        if resp.status_code not in (404, 405):
            resp.raise_for_status()
        # Minimal JSON-RPC
        resp = await client.post(
            base_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
            headers=hdrs,
        )
        if resp.status_code >= 400:
            resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "error" in data:
            err = data["error"]
            message = err.get("message") if isinstance(err, dict) else str(err)
            raise RuntimeError(f"MCP tools/list failed: {message}")
        result = data.get("result") if isinstance(data, dict) else None
        if isinstance(result, dict) and isinstance(result.get("tools"), list):
            return result["tools"]
        if isinstance(result, list):
            return result
        raise RuntimeError("MCP tools/list returned no tools")


async def _http_tools_call(
    base_url: str,
    name: str,
    arguments: dict[str, Any],
    *,
    headers: Optional[dict[str, str]] = None,
) -> str:
    hdrs = dict(headers or {})
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{base_url}/api/v1/mcp/tools/call",
            json={"name": name, "arguments": arguments},
            headers=hdrs,
        )
        if resp.status_code < 400:
            data = resp.json()
            if isinstance(data, dict):
                if "content" in data:
                    return str(data["content"])
                if "result" in data:
                    return str(data["result"])
            return str(data)
        if resp.status_code not in (404, 405):
            resp.raise_for_status()
        resp = await client.post(
            base_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
            headers=hdrs,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            if "error" in data:
                err = data["error"]
                message = err.get("message") if isinstance(err, dict) else str(err)
                raise RuntimeError(f"MCP tools/call failed: {message}")
            if "result" in data:
                result = data["result"]
                if isinstance(result, dict) and "content" in result:
                    blocks = result["content"]
                    if isinstance(blocks, list):
                        for block in blocks:
                            if isinstance(block, dict) and block.get("type") == "text":
                                return str(block.get("text", ""))
                return str(result)
        return str(data)
