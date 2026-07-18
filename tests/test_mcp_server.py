"""MCP REST shim + streamable HTTP transport tests."""

from __future__ import annotations

import json

from synthora.api import mcp_server
from synthora.api.settings import settings

from tests.test_platform import fake_run_config, make_executor

pytest_plugins = ("tests.test_platform",)


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


def test_mcp_rest_start_research_with_config(platform):
    client, _ = platform
    resp = client.post(
        "/api/v1/mcp/tools/call",
        json={
            "name": "start_research",
            "arguments": {
                "question": "Configurable MCP run",
                "pipeline_id": "fast_research",
                "config": {**fake_run_config(), "max_react_tool_calls": 2},
            },
        },
    )
    assert resp.status_code == 200
    payload = json.loads(resp.json()["content"])
    assert payload["run_id"]
    run = client.get(f"/api/v1/research/{payload['run_id']}").json()
    assert run["config"]["max_react_tool_calls"] == 2


def test_mcp_streamable_tools_list(platform):
    client, _ = platform
    headers = {"Accept": "application/json, text/event-stream"}
    init = client.post(
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
        headers=headers,
    )
    assert init.status_code == 200, init.text
    session_id = init.headers.get("mcp-session-id")
    if session_id:
        headers = {**headers, "Mcp-Session-Id": session_id}
    resp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    tools = resp.json().get("result", {}).get("tools", [])
    names = {t["name"] for t in tools}
    assert names == {
        "start_research",
        "get_run_status",
        "get_report",
        "search_documents",
    }
    start = next(t for t in tools if t["name"] == "start_research")
    assert "config" in start.get("inputSchema", {}).get("properties", {})


def test_mcp_streamable_tools_call(platform):
    client, app = platform
    headers = {"Accept": "application/json, text/event-stream"}
    init = client.post(
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
        headers=headers,
    )
    assert init.status_code == 200
    session_id = init.headers.get("mcp-session-id")
    if session_id:
        headers = {**headers, "Mcp-Session-Id": session_id}
    started = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "start_research",
                "arguments": {
                    "question": "Streamable MCP start",
                    "pipeline_id": "fast_research",
                    "config": fake_run_config(),
                },
            },
        },
        headers=headers,
    )
    assert started.status_code == 200, started.text
    content_blocks = started.json().get("result", {}).get("content", [])
    text = next(
        (b["text"] for b in content_blocks if b.get("type") == "text"), None
    )
    assert text
    payload = json.loads(text)
    run_id = payload["run_id"]
    executor = make_executor(app)
    client.portal.call(executor.execute, run_id)
    report = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "get_report", "arguments": {"run_id": run_id}},
        },
        headers=headers,
    )
    assert report.status_code == 200
    report_text = next(
        (b["text"] for b in report.json()["result"]["content"] if b.get("type") == "text"),
        "",
    )
    assert "Integration Report" in report_text


def test_mcp_transport_security_from_settings():
    settings.mcp_dns_rebinding_protection = False
    disabled = mcp_server.build_mcp_transport_security()
    assert disabled.enable_dns_rebinding_protection is False

    settings.mcp_dns_rebinding_protection = True
    settings.mcp_allowed_hosts = "localhost:*, api.example.com:*"
    settings.mcp_allowed_origins = "https://app.example.com"
    enabled = mcp_server.build_mcp_transport_security()
    assert enabled.enable_dns_rebinding_protection is True
    assert "localhost:*" in enabled.allowed_hosts
    assert "api.example.com:*" in enabled.allowed_hosts
    assert "https://app.example.com" in enabled.allowed_origins

    settings.mcp_dns_rebinding_protection = False
    settings.mcp_allowed_hosts = ""
    settings.mcp_allowed_origins = ""

