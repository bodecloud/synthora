"""Regression tests for zero-gap closures: cancel, empty engines, MCP auth, news."""

from __future__ import annotations

import pytest
from synthora.adapters import search_engine_registry
from synthora.adapters.mcp_client import _auth_headers
from synthora.core.models import NewsSubscription, ResearchRun, RunConfig, RunStatus
from synthora.persistence import NewsRepository, RunRepositorySQL
from synthora.worker.news import fetch_subscription_news

from tests.test_platform import fake_run_config, make_executor

pytest_plugins = ("tests.test_platform",)


def test_cancel_marks_run_cancelled(platform):
    client, _ = platform
    created = client.post(
        "/api/v1/research",
        json={
            "question": "cancel me",
            "pipeline_id": "fast_research",
            "config": fake_run_config(),
        },
    )
    assert created.status_code == 202
    run_id = created.json()["run_id"]
    cancelled = client.post(f"/api/v1/research/{run_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    detail = client.get(f"/api/v1/research/{run_id}").json()
    assert detail["status"] == "cancelled"


def test_steer_rejects_terminal_status(platform):
    client, app = platform
    created = client.post(
        "/api/v1/research",
        json={
            "question": "steer me",
            "pipeline_id": "fast_research",
            "config": fake_run_config(),
        },
    )
    run_id = created.json()["run_id"]
    client.post(f"/api/v1/research/{run_id}/cancel")
    steered = client.post(
        f"/api/v1/research/{run_id}/steer",
        json={"message": "focus on cost"},
    )
    assert steered.status_code == 409


def test_empty_search_engines_fail_loud(platform):
    _, app = platform
    executor = make_executor(app)

    async def _run():
        runs = RunRepositorySQL(executor.db)
        run = ResearchRun(
            question="empty engines",
            pipeline_id="fast_research",
            workspace_id="default",
            status=RunStatus.QUEUED,
            config=RunConfig(search_engines=["none"]),
        )
        await runs.create(run)
        with pytest.raises(RuntimeError, match="No usable search engines"):
            executor.build_context(run)

    client, _ = platform
    # TestClient from starlette exposes portal for async
    client.portal.call(_run)


def test_mcp_auth_headers_prefer_config_token():
    headers = _auth_headers(
        {"token": "cfg-token"},
        {"url": "http://127.0.0.1:8000"},
    )
    assert headers["Authorization"] == "Bearer cfg-token"
    headers = _auth_headers(
        {},
        {"url": "http://127.0.0.1:8000", "token": "server-token"},
    )
    assert headers["Authorization"] == "Bearer server-token"


@pytest.mark.asyncio
async def test_news_does_not_advance_last_run_on_total_failure(db):
    repo = NewsRepository(db)
    sub = NewsSubscription(
        workspace_id="default",
        query="x",
        cadence="daily",
        last_run_at=None,
    )
    await repo.create_subscription(sub)

    class Boom:
        name = "boom"

        async def search(self, query: str, *, max_results: int = 5):
            raise RuntimeError("network down")

    search_engine_registry.register("boom", lambda: Boom())
    items = await fetch_subscription_news(repo, sub, engine_names=["boom"])
    assert items == []
    refreshed = await repo.get_subscription(sub.id)
    assert refreshed is not None
    assert refreshed.last_run_at is None


@pytest.mark.asyncio
async def test_nested_researcher_accepts_thread_id():
    """Nested graphs must support thread_id (MemorySaver), not bare compile()."""
    from synthora.adapters.llm import FakeRoutingModel
    from synthora.adapters.search_engines import FakeSearchEngine
    from synthora.core.models import RunConfig
    from synthora.orchestration.context import ResearchContext
    from synthora.orchestration.graphs import build_researcher_graph

    ctx = ResearchContext(
        run_id="nested-smoke",
        config=RunConfig(
            search_engines=["fake"],
            max_react_tool_calls=2,
            allow_clarification=False,
        ),
        planner=FakeRoutingModel(),
        researcher=FakeRoutingModel(),
        compressor=FakeRoutingModel(),
        writer=FakeRoutingModel(),
        critic=FakeRoutingModel(),
        engines=[FakeSearchEngine()],
    )
    graph = build_researcher_graph()
    result = await graph.ainvoke(
        {"topic": "smoke topic", "tool_calls": 0},
        config={
            "configurable": {"synthora_ctx": ctx, "thread_id": "nested-smoke:researcher"},
            "recursion_limit": 50,
        },
    )
    assert result.get("findings") or result.get("compressed")
