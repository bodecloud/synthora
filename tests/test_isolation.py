"""Security / isolation regressions from Tier-2 parity review."""

from __future__ import annotations

import json

import pytest
from synthora.adapters.document_index import document_index
from synthora.adapters.mcp_client import validate_mcp_url
from synthora.adapters.search_engines import CollectionEngine
from synthora.adapters.workspace_context import reset_workspace_id, set_workspace_id
from synthora.api.settings import settings
from synthora.core.models import NewsItem, NewsSubscription
from synthora.persistence import NewsRepository, WorkspaceRepository

from tests.test_platform import fake_run_config

pytest_plugins = ("tests.test_platform",)


@pytest.mark.asyncio
async def test_collection_engine_does_not_leak_across_workspaces():
    document_index.clear()
    document_index.upsert(
        "ws-a",
        {
            "id": "doc-a",
            "title": "Secret A",
            "url": "collection://a",
            "content": "alpha payload unique-to-a",
        },
    )
    document_index.upsert(
        "ws-b",
        {
            "id": "doc-b",
            "title": "Secret B",
            "url": "collection://b",
            "content": "beta payload unique-to-b",
        },
    )
    engine = CollectionEngine(documents=[])
    token = set_workspace_id("ws-a")
    try:
        results = await engine.search("unique-to-b", max_results=5)
        assert results == []
        results_a = await engine.search("unique-to-a", max_results=5)
        assert len(results_a) == 1
        assert "unique-to-a" in (results_a[0].content or "")
    finally:
        reset_workspace_id(token)
        document_index.clear()


@pytest.mark.asyncio
async def test_news_items_always_scoped_by_workspace(db):
    await WorkspaceRepository(db).ensure_default()
    await WorkspaceRepository(db).ensure_for_owner("other-user", name="other")
    news = NewsRepository(db)
    mine = NewsSubscription(workspace_id="default", query="mine", cadence="daily")
    theirs = NewsSubscription(
        workspace_id="other-user", query="theirs", cadence="daily"
    )
    await news.create_subscription(mine)
    await news.create_subscription(theirs)
    await news.add_items(
        [
            NewsItem(
                subscription_id=theirs.id,
                title="Leaked",
                url="https://evil.example/leak",
                summary="should not appear",
            )
        ]
    )
    leaked = await news.list_items(
        workspace_id="default", subscription_id=theirs.id, limit=50
    )
    assert leaked == []


def test_mcp_url_blocks_ssrf_targets(monkeypatch):
    monkeypatch.delenv("SYNTHORA_MCP_ALLOWLIST", raising=False)
    assert validate_mcp_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000"
    with pytest.raises(ValueError, match="private|ALLOWLIST|allowlist"):
        validate_mcp_url("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(ValueError, match="ALLOWLIST|allowlist"):
        validate_mcp_url("https://evil.example/mcp")
    monkeypatch.setenv("SYNTHORA_MCP_ALLOWLIST", "evil.example")
    assert validate_mcp_url("https://evil.example/mcp") == "https://evil.example/mcp"


def test_session_auth_workspace_and_ws_isolation(platform):
    client, _app = platform
    settings.auth_mode = "session"
    settings.secret_key = "test-secret-not-default"
    try:
        alice = client.post(
            "/api/v1/auth/register",
            json={"username": "alice_iso", "password": "supersecret"},
        )
        assert alice.status_code == 201
        alice_token = alice.json()["token"]
        alice_id = alice.json()["user_id"]
        alice_h = {"Authorization": f"Bearer {alice_token}"}

        bob = client.post(
            "/api/v1/auth/register",
            json={"username": "bob_iso", "password": "supersecret"},
        )
        assert bob.status_code == 201
        bob_token = bob.json()["token"]
        bob_h = {"Authorization": f"Bearer {bob_token}"}

        session = client.post(
            "/api/v1/sessions",
            headers=alice_h,
            json={"title": "Alice session"},
        )
        assert session.status_code == 201
        assert session.json()["workspace_id"] == alice_id

        run = client.post(
            "/api/v1/research",
            headers=alice_h,
            json={
                "question": "alice only",
                "pipeline_id": "fast_research",
                "config": fake_run_config(),
            },
        )
        assert run.status_code == 202
        run_id = run.json()["run_id"]

        assert (
            client.get(f"/api/v1/research/{run_id}", headers=bob_h).status_code == 404
        )
        # Alice can read events over HTTP; Bob cannot.
        assert (
            client.get(
                f"/api/v1/research/{run_id}/events", headers=alice_h
            ).status_code
            == 200
        )
        assert (
            client.get(
                f"/api/v1/research/{run_id}/events", headers=bob_h
            ).status_code
            == 404
        )

        with pytest.raises(Exception):
            with client.websocket_connect(
                f"/api/v1/research/{run_id}/events/ws"
            ) as ws:
                ws.receive_json()

        with pytest.raises(Exception):
            with client.websocket_connect(
                f"/api/v1/research/{run_id}/events/ws?token={bob_token}"
            ) as ws:
                ws.receive_json()

        # MCP REST shim must not leak Alice's run to Bob.
        bob_mcp = client.post(
            "/api/v1/mcp/tools/call",
            headers=bob_h,
            json={"name": "get_run_status", "arguments": {"run_id": run_id}},
        )
        assert bob_mcp.status_code == 404

        alice_mcp = client.post(
            "/api/v1/mcp/tools/call",
            headers=alice_h,
            json={"name": "get_run_status", "arguments": {"run_id": run_id}},
        )
        assert alice_mcp.status_code == 200
        assert json.loads(alice_mcp.json()["content"])["run_id"] == run_id

        # Streamable MCP must also reject cross-workspace status reads.
        stream_headers = {
            **alice_h,
            "Accept": "application/json, text/event-stream",
        }
        init = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "iso-test", "version": "0.1"},
                },
            },
            headers=stream_headers,
        )
        assert init.status_code == 200
        session_id = init.headers.get("mcp-session-id")
        bob_stream_h = {
            **bob_h,
            "Accept": "application/json, text/event-stream",
        }
        if session_id:
            bob_stream_h["Mcp-Session-Id"] = session_id
        bob_stream = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "get_run_status",
                    "arguments": {"run_id": run_id},
                },
            },
            headers=bob_stream_h,
        )
        assert bob_stream.status_code == 200
        bob_text = next(
            (
                b["text"]
                for b in bob_stream.json()["result"]["content"]
                if b.get("type") == "text"
            ),
            "",
        )
        assert "run not found" in json.loads(bob_text)["error"]
    finally:
        settings.auth_mode = "none"
        settings.secret_key = "change-me"


def test_secret_key_guard_for_session_auth():
    from synthora.api.settings import Settings

    insecure = Settings(auth_mode="session", secret_key="change-me")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        insecure.assert_secure_for_auth()
    Settings(auth_mode="session", secret_key="real-secret").assert_secure_for_auth()
