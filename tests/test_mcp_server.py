"""MCP REST shim + streamable HTTP transport tests."""

from __future__ import annotations

import json


def test_mcp_rest_tools_list(platform):
    client, _ = platform
    resp = client.post("/api/v1/mcp/tools/list", json={})
    assert resp.status_code == 200
    names = {t["name"] for t in resp.json()["tools"]}
    assert names == {
        "start_research",
        "get_run_status",
        "get_report",
        "search_documents",
    }


def test_mcp_rest_start_research(platform):
    client, _ = platform
    resp = client.post(
        "/api/v1/mcp/tools/call",
        json={
            "name": "start_research",
            "arguments": {"question": "What is quantum computing?"},
        },
    )
    assert resp.status_code == 200
    payload = json.loads(resp.json()["content"])
    assert payload["run_id"]
    assert payload["status"] == "queued"


def test_mcp_streamable_initialize(platform):
    client, _ = platform
    resp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "synthora-test", "version": "0.1"},
            },
        },
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("result", {}).get("serverInfo", {}).get("name") == "Synthora"
