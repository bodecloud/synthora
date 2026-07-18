"""Outbound MCP client HTTP fallback tests."""

from __future__ import annotations

import json

import httpx
import pytest
from httpx import ASGITransport
from synthora.adapters.mcp_client import (
    _http_tools_call,
    _http_tools_list,
    load_mcp_tools,
)

from tests.test_platform import fake_run_config

pytest_plugins = ("tests.test_platform",)


@pytest.fixture
def route_mcp_http(platform, monkeypatch):
    _client, app = platform

    class _RoutingAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = ASGITransport(app=app)
            kwargs["base_url"] = "http://127.0.0.1:8000"
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(
        "synthora.adapters.mcp_client.httpx.AsyncClient", _RoutingAsyncClient
    )


@pytest.mark.asyncio
async def test_http_tools_list_via_rest(route_mcp_http):
    tools = await _http_tools_list("http://127.0.0.1:8000", headers={})
    names = {t["name"] for t in tools}
    assert names == {
        "start_research",
        "get_run_status",
        "get_report",
        "search_documents",
    }


@pytest.mark.asyncio
async def test_http_tools_call_via_rest(route_mcp_http):
    content = await _http_tools_call(
        "http://127.0.0.1:8000",
        "start_research",
        {
            "question": "MCP outbound test",
            "pipeline_id": "fast_research",
            "config": fake_run_config(),
        },
    )
    payload = json.loads(content)
    assert payload["run_id"]
    assert payload["status"] == "queued"


@pytest.mark.asyncio
async def test_http_tools_call_raises_on_jsonrpc_error(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/v1/mcp/tools/call"):
            return httpx.Response(404)
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "error": {"message": "denied"}},
        )

    transport = httpx.MockTransport(handler)

    class _MockAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            kwargs["base_url"] = "http://evil.test"
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(
        "synthora.adapters.mcp_client.httpx.AsyncClient", _MockAsyncClient
    )
    with pytest.raises(RuntimeError, match="tools/call failed"):
        await _http_tools_call("http://evil.test", "x", {})


@pytest.mark.asyncio
async def test_load_mcp_tools_http_fallback(route_mcp_http):
    tools = await load_mcp_tools(
        {"servers": [{"url": "http://127.0.0.1:8000", "transport": "http"}]}
    )
    assert {t.name for t in tools} == {
        "start_research",
        "get_run_status",
        "get_report",
        "search_documents",
    }
