"""U6: platform integration — API, queue, executor, auth, WebSocket, SDK paths."""

from __future__ import annotations

import json

import fakeredis.aioredis
import pytest
import synthora.api.main as api_main
from fastapi.testclient import TestClient
from synthora.adapters import llm_registry, search_engine_registry
from synthora.api.settings import settings
from synthora.worker.executor import RunExecutor

from tests.conftest import FakeSearchEngine

SEARCH = json.dumps({"action": "search", "query": "q"})


class RoutingFakeModel:
    """Stateless-ish fake LLM routed by system prompt (works for every role).

    Supervisor is stateful: first call conducts research, later calls complete.
    """

    def __init__(self) -> None:
        self._supervisor_calls = 0

    async def complete(self, messages, *, temperature=0.3, max_tokens=None) -> str:
        system = messages[0]["content"]
        if "Rewrite the research request" in system:
            return "integration test brief"
        if "researcher with a search tool" in system:
            user = messages[-1]["content"] if len(messages) > 1 else ""
            findings = ""
            if "Findings:\n" in user:
                findings = user.split("Findings:\n", 1)[-1].strip()
            if findings and findings != "(none yet)":
                return json.dumps({"action": "complete", "reflection": "done"})
            return SEARCH
        if "research supervisor" in system:
            self._supervisor_calls += 1
            if self._supervisor_calls <= 1:
                return json.dumps(
                    {
                        "action": "conduct_research",
                        "topics": ["integration focus topic"],
                    }
                )
            return json.dumps({"action": "research_complete"})
        if "Compress these research findings" in system:
            return "compressed findings [1]"
        if "final research report" in system:
            return "# Integration Report\n\nA finding [1].\n\n## Sources"
        if "Decompose the research topic" in system:
            return "sub query"
        if "Summarize the web page" in system:
            return "page summary for research notes"
        if "academic literature search" in system:
            return "quantum error correction\nsurface code\nthreshold theorem"
        if "Generate 2-3 concrete" in system or "investigable hypotheses" in system:
            return "hypothesis A: X holds under Y\nhypothesis B: Z is the limiter"
        if "Identify the most important unanswered" in system or "knowledge gaps" in system:
            # Empty gaps → autonomous pipeline synthesizes after one cycle.
            return ""
        if "academic peer reviewer" in system:
            return "1. Strengthen citation density in the findings section."
        if "perspective" in system.lower() or "expert persona" in system.lower():
            return json.dumps(
                {
                    "perspectives": [
                        {
                            "name": "Historian",
                            "focus": "history",
                            "expertise": "archives",
                        },
                        {
                            "name": "Engineer",
                            "focus": "systems",
                            "expertise": "reliability",
                        },
                    ]
                }
            )
        if (
            "hierarchical outline" in system.lower()
            or "JSON outline" in system
            or "Design a report outline" in system
        ):
            return json.dumps(
                {
                    "title": "Report",
                    "sections": [
                        {"title": "Background", "description": "context"},
                        {"title": "Findings", "description": "results"},
                    ],
                }
            )
        if "rigorous reviewer" in system or "Critique" in system:
            return "- tighten sourcing"
        if "verify sources" in system.lower() or "You verify sources" in system:
            return json.dumps({"verified": [1], "rejected": []})
        if (
            "Deduplicate" in system
            or "polished Markdown" in system
            or "citation markers intact" in system
        ):
            return messages[-1]["content"] if len(messages) > 1 else "polished"
        return "ANSWER: insight [1]"


@pytest.fixture
def platform(tmp_path, monkeypatch):
    """API TestClient wired to a temp SQLite DB and fakeredis, with fake
    LLM/search providers registered."""
    settings.database_url = f"sqlite+aiosqlite:///{tmp_path}/synthora-test.db"
    settings.auth_mode = "none"

    fake_redis = fakeredis.aioredis.FakeRedis()
    monkeypatch.setattr(
        api_main.aioredis, "from_url", lambda url: fake_redis
    )

    llm_registry.register("fake", lambda m: RoutingFakeModel())
    search_engine_registry.register("fake", FakeSearchEngine)

    with TestClient(api_main.app) as client:
        yield client, api_main.app


def fake_run_config() -> dict:
    return {
        "planner_model": "fake:m",
        "researcher_model": "fake:m",
        "compressor_model": "fake:m",
        "writer_model": "fake:m",
        "critic_model": "fake:m",
        "search_engines": ["fake"],
        "search_strategy": "source_based",
        "max_react_tool_calls": 1,
    }


def make_executor(app) -> RunExecutor:
    return RunExecutor(app.state.db, app.state.queue)


# ------------------------------------------------------------------ health/catalog


def test_health_and_ready(platform):
    client, _ = platform
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}


def test_catalog_endpoints(platform):
    client, _ = platform
    pipelines = client.get("/api/v1/pipelines").json()["pipelines"]
    assert {p["id"] for p in pipelines} == {
        "fast_research",
        "deep_research",
        "academic_research",
        "autonomous_research",
    }
    providers = client.get("/api/v1/providers").json()
    assert "openai" in providers["llm_providers"]
    assert "searxng" in providers["search_engines"]
    assert "source_based" in providers["search_strategies"]


# ------------------------------------------------------------------ lifecycle


def test_start_progress_complete_lifecycle(platform):
    client, app = platform
    resp = client.post(
        "/api/v1/research",
        json={
            "question": "What is integration testing?",
            "pipeline_id": "fast_research",
            "config": fake_run_config(),
        },
    )
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    assert client.get(f"/api/v1/research/{run_id}").json()["status"] == "queued"

    # worker turn: dequeue and execute
    executor = make_executor(app)

    async def drive():
        job = await app.state.queue.dequeue(timeout=1)
        assert job["run_id"] == run_id
        return await executor.execute(run_id)

    run = client.portal.call(drive)
    assert run.status.value == "completed"

    detail = client.get(f"/api/v1/research/{run_id}").json()
    assert detail["status"] == "completed"
    assert detail["brief"] == "integration test brief"

    report = client.get(f"/api/v1/research/{run_id}/report").json()
    assert report["report_markdown"].startswith("# Integration Report")
    assert report["citations"]

    events = client.get(f"/api/v1/research/{run_id}/events").json()["events"]
    types = [e["type"] for e in events]
    assert "status" in types and "done" in types

    runs = client.get("/api/v1/research").json()["runs"]
    assert runs[0]["id"] == run_id


def test_unknown_pipeline_rejected(platform):
    client, _ = platform
    resp = client.post(
        "/api/v1/research", json={"question": "q?", "pipeline_id": "bogus"}
    )
    assert resp.status_code == 422


def test_cancel_before_execution(platform):
    client, app = platform
    run_id = client.post(
        "/api/v1/research",
        json={
            "question": "cancel me",
            "pipeline_id": "fast_research",
            "config": fake_run_config(),
        },
    ).json()["run_id"]
    assert (
        client.post(f"/api/v1/research/{run_id}/cancel").json()["cancel_requested"]
        is True
    )
    executor = make_executor(app)
    run = client.portal.call(executor.execute, run_id)
    assert run.status.value == "cancelled"
    # double-cancel of a finished run conflicts
    assert client.post(f"/api/v1/research/{run_id}/cancel").status_code == 409


def test_steer_lands_in_queue(platform):
    client, app = platform
    run_id = client.post(
        "/api/v1/research",
        json={
            "question": "steer me",
            "pipeline_id": "fast_research",
            "config": fake_run_config(),
        },
    ).json()["run_id"]
    client.post(f"/api/v1/research/{run_id}/steer", json={"message": "focus on cost"})

    async def drain():
        return await app.state.queue.drain_steering(run_id)

    assert client.portal.call(drain) == ["focus on cost"]


def test_websocket_replays_events(platform):
    client, app = platform
    run_id = client.post(
        "/api/v1/research",
        json={
            "question": "ws test",
            "pipeline_id": "fast_research",
            "config": fake_run_config(),
        },
    ).json()["run_id"]
    executor = make_executor(app)
    client.portal.call(executor.execute, run_id)

    with client.websocket_connect(f"/api/v1/research/{run_id}/events/ws") as ws:
        received = []
        while True:
            try:
                received.append(ws.receive_json())
            except Exception:
                break
        types = [e["type"] for e in received]
        assert types[0] == "status"
        assert types[-1] == "done"


def test_failed_run_reports_error(platform):
    client, app = platform

    class ExplodingModel:
        async def complete(self, messages, *, temperature=0.3, max_tokens=None):
            raise RuntimeError("provider exploded")

    llm_registry.register("exploding", lambda m: ExplodingModel())
    config = {**fake_run_config(), "planner_model": "exploding:m"}
    run_id = client.post(
        "/api/v1/research",
        json={"question": "will fail", "pipeline_id": "fast_research", "config": config},
    ).json()["run_id"]
    executor = make_executor(app)
    run = client.portal.call(executor.execute, run_id)
    assert run.status.value == "failed"
    assert "provider exploded" in run.error
    detail = client.get(f"/api/v1/research/{run_id}").json()
    assert detail["status"] == "failed"


def test_export_markdown_and_html(platform):
    client, app = platform
    run_id = client.post(
        "/api/v1/research",
        json={
            "question": "export test",
            "pipeline_id": "fast_research",
            "config": fake_run_config(),
        },
    ).json()["run_id"]
    executor = make_executor(app)
    client.portal.call(executor.execute, run_id)

    md = client.get(f"/api/v1/research/{run_id}/export?format=markdown")
    assert md.status_code == 200
    assert md.headers["content-type"].startswith("text/markdown")
    assert "attachment" in md.headers["content-disposition"]
    assert md.text.startswith("# Integration Report")

    html = client.get(f"/api/v1/research/{run_id}/export?format=html")
    assert html.status_code == 200
    assert "<h1>Integration Report</h1>" in html.text
    assert "export test" in html.text  # question used as document title

    pdf = client.get(f"/api/v1/research/{run_id}/export?format=pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert pdf.content[:4] == b"%PDF"
    arts = client.get(f"/api/v1/research/{run_id}/report").json()["artifacts"]
    assert any(a["kind"] == "export_pdf" for a in arts)

    bad = client.get(f"/api/v1/research/{run_id}/export?format=docx")
    assert bad.status_code == 422


# ------------------------------------------------------------------ settings / mcp / sessions


def test_provider_settings_roundtrip(platform):
    client, app = platform
    assert client.get("/api/v1/settings").json()["settings"] == []
    put = client.put(
        "/api/v1/settings/openai",
        json={
            "value": {
                "model": "gpt-4o-mini",
                "enabled": True,
                "api_key": "sk-test",
            }
        },
    )
    assert put.status_code == 200
    assert put.json()["value"]["model"] == "gpt-4o-mini"
    assert put.json()["value"]["api_key"] == "***"
    got = client.get("/api/v1/settings/openai").json()
    assert got["key"] == "openai"
    assert got["value"]["enabled"] is True
    assert got["value"]["api_key"] == "***"
    listed = client.get("/api/v1/settings").json()["settings"]
    assert len(listed) == 1

    # Masked PUT must not clobber the stored secret.
    client.put(
        "/api/v1/settings/openai",
        json={"value": {"api_key": "***", "model": "gpt-4o"}},
    )
    assert client.get("/api/v1/settings/openai").json()["value"]["model"] == "gpt-4o"

    from synthora.persistence import ProviderSettingsRepository

    async def load():
        row = await ProviderSettingsRepository(app.state.db).get("default", "openai")
        return row.value if row else {}

    stored = client.portal.call(load)
    assert stored["api_key"] == "sk-test"
    assert stored["model"] == "gpt-4o"

def test_provider_settings_overlay_feeds_llm_resolve(platform, monkeypatch):
    """Workspace settings must win over env when resolving credentials."""
    from synthora.adapters.llm import OpenAICompatibleModel
    from synthora.adapters.provider_settings_context import (
        reset_provider_settings,
        set_provider_settings,
    )
    from synthora.persistence import ProviderSettingsRepository

    client, app = platform
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client.put(
        "/api/v1/settings/openai",
        json={
            "value": {
                "api_key": "from-workspace",
                "base_url": "https://example.test/v1",
            }
        },
    )

    async def load():
        rows = await ProviderSettingsRepository(app.state.db).list_settings("default")
        return {r.key: dict(r.value or {}) for r in rows}

    overlay = client.portal.call(load)
    token = set_provider_settings(overlay)
    try:
        model = OpenAICompatibleModel("gpt-test")
        assert model.api_key == "from-workspace"
        assert model.base_url == "https://example.test/v1"
    finally:
        reset_provider_settings(token)

def test_mcp_tools_list_and_call(platform):
    client, app = platform
    tools = client.post("/api/v1/mcp/tools/list").json()["tools"]
    names = {t["name"] for t in tools}
    assert names == {
        "start_research",
        "get_run_status",
        "get_report",
        "search_documents",
    }

    started = client.post(
        "/api/v1/mcp/tools/call",
        json={
            "name": "start_research",
            "arguments": {
                "question": "What is MCP?",
                "pipeline_id": "fast_research",
                "config": fake_run_config(),
            },
        },
    )
    assert started.status_code == 200
    payload = json.loads(started.json()["content"])
    run_id = payload["run_id"]

    status = client.post(
        "/api/v1/mcp/tools/call",
        json={"name": "get_run_status", "arguments": {"run_id": run_id}},
    )
    assert json.loads(status.json()["content"])["status"] == "queued"

    executor = make_executor(app)
    client.portal.call(executor.execute, run_id)
    report = client.post(
        "/api/v1/mcp/tools/call",
        json={"name": "get_report", "arguments": {"run_id": run_id}},
    )
    assert "Integration Report" in report.json()["content"]

    docs = client.post(
        "/api/v1/mcp/tools/call",
        json={
            "name": "search_documents",
            "arguments": {"query": "nothing-here-yet", "max_results": 2},
        },
    )
    assert docs.status_code == 200
    assert "results" in json.loads(docs.json()["content"])


def test_sessions_and_resume_api(platform):
    client, app = platform
    session = client.post(
        "/api/v1/sessions",
        json={"title": "Clarify session", "tags": ["test"]},
    )
    assert session.status_code == 201
    session_id = session.json()["id"]
    assert client.get("/api/v1/sessions").json()["sessions"][0]["id"] == session_id

    # resume rejected unless awaiting_input
    run_id = client.post(
        "/api/v1/research",
        json={
            "question": "resume without interrupt",
            "pipeline_id": "fast_research",
            "session_id": session_id,
            "config": fake_run_config(),
        },
    ).json()["run_id"]
    assert (
        client.post(
            f"/api/v1/research/{run_id}/resume", json={"answer": "nope"}
        ).status_code
        == 409
    )

    detail = client.get(f"/api/v1/sessions/{session_id}").json()
    assert detail["runs"][0]["id"] == run_id

    assert client.delete(f"/api/v1/sessions/{session_id}").json()["deleted"] is True


# ------------------------------------------------------------------ auth


def test_session_auth_flow(platform):
    client, _ = platform
    settings.auth_mode = "session"
    try:
        # unauthenticated request rejected
        assert client.get("/api/v1/research").status_code == 401

        resp = client.post(
            "/api/v1/auth/register",
            json={"username": "alice", "password": "supersecret"},
        )
        assert resp.status_code == 201
        token = resp.json()["token"]

        # duplicate username rejected
        assert (
            client.post(
                "/api/v1/auth/register",
                json={"username": "alice", "password": "supersecret"},
            ).status_code
            == 409
        )
        # wrong password rejected
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"username": "alice", "password": "wrongpassword"},
            ).status_code
            == 401
        )
        # login works
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "supersecret"},
        )
        assert login.status_code == 200

        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/v1/research", headers=headers).status_code == 200
    finally:
        settings.auth_mode = "none"


def test_auth_endpoints_disabled_in_none_mode(platform):
    client, _ = platform
    resp = client.post(
        "/api/v1/auth/register", json={"username": "bob", "password": "password123"}
    )
    assert resp.status_code == 400


# ------------------------------------------------------------------ follow-up / chat


def test_followup_links_session_and_parent_extra(platform):
    client, app = platform
    parent_id = client.post(
        "/api/v1/research",
        json={
            "question": "What is quantum computing?",
            "pipeline_id": "fast_research",
            "config": fake_run_config(),
        },
    ).json()["run_id"]
    executor = make_executor(app)
    client.portal.call(executor.execute, parent_id)

    parent = client.get(f"/api/v1/research/{parent_id}").json()
    assert parent["session_id"] is None

    follow = client.post(
        f"/api/v1/research/{parent_id}/followup",
        json={"question": "How does entanglement work?", "pipeline_id": "fast_research"},
    )
    assert follow.status_code == 202
    body = follow.json()
    assert body["parent_run_id"] == parent_id
    assert body["session_id"]
    child_id = body["run_id"]

    # parent now shares the session
    parent_after = client.get(f"/api/v1/research/{parent_id}").json()
    assert parent_after["session_id"] == body["session_id"]

    child = client.get(f"/api/v1/research/{child_id}").json()
    assert child["session_id"] == body["session_id"]
    extra = child["config"]["extra"]
    assert extra["parent_run_id"] == parent_id
    assert "parent_brief" in extra
    assert extra["parent_brief"]  # seeded from completed parent brief

    # worker can execute the follow-up like any other run
    child_run = client.portal.call(executor.execute, child_id)
    assert child_run.status.value == "completed"


def test_chat_creates_fast_research_run(platform):
    client, _ = platform
    resp = client.post("/api/v1/chat", json={"message": "Hello research"})
    assert resp.status_code == 202
    body = resp.json()
    assert body["run_id"]
    assert body["session_id"]
    detail = client.get(f"/api/v1/research/{body['run_id']}").json()
    assert detail["pipeline_id"] == "fast_research"
    assert detail["question"] == "Hello research"
    assert detail["session_id"] == body["session_id"]

    again = client.post(
        "/api/v1/chat",
        json={"message": "Follow the thread", "session_id": body["session_id"]},
    )
    assert again.status_code == 202
    assert again.json()["session_id"] == body["session_id"]


def test_deep_research_lifecycle_via_worker(platform):
    """Deep research must complete end-to-end through API + worker with fakes."""
    client, app = platform
    cfg = fake_run_config()
    cfg.update(
        {
            "max_react_tool_calls": 1,
            "max_discourse_turns": 3,
            "num_perspectives": 2,
            "max_researcher_iterations": 2,
            "allow_clarification": False,
        }
    )
    resp = client.post(
        "/api/v1/research",
        json={
            "question": "Deep integration topic?",
            "pipeline_id": "deep_research",
            "config": cfg,
        },
    )
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    executor = make_executor(app)

    async def drive():
        job = await app.state.queue.dequeue(timeout=1)
        assert job["run_id"] == run_id
        return await executor.execute(run_id)

    run = client.portal.call(drive)
    assert run.status.value == "completed", run.error
    report = client.get(f"/api/v1/research/{run_id}/report").json()
    assert report["report_markdown"]
    discourse = client.get(f"/api/v1/research/{run_id}/discourse").json()["turns"]
    assert discourse


def _drive_pipeline(platform, pipeline_id: str, question: str, **cfg_extra):
    client, app = platform
    cfg = fake_run_config()
    cfg.update(
        {
            "max_react_tool_calls": 1,
            "max_discourse_turns": 2,
            "num_perspectives": 2,
            "max_researcher_iterations": 2,
            "max_autonomous_cycles": 1,
            "allow_clarification": False,
            **cfg_extra,
        }
    )
    resp = client.post(
        "/api/v1/research",
        json={
            "question": question,
            "pipeline_id": pipeline_id,
            "config": cfg,
        },
    )
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]
    executor = make_executor(app)

    async def drive():
        job = await app.state.queue.dequeue(timeout=1)
        assert job["run_id"] == run_id
        return await executor.execute(run_id)

    run = client.portal.call(drive)
    assert run.status.value == "completed", run.error
    report = client.get(f"/api/v1/research/{run_id}/report").json()
    assert report["report_markdown"]
    return run_id, report


def test_academic_research_lifecycle_via_worker(platform):
    run_id, report = _drive_pipeline(
        platform, "academic_research", "Academic literature question?"
    )
    assert "## Bibliography" in report["report_markdown"]
    citations = report.get("citations") or []
    assert citations


def test_autonomous_research_lifecycle_via_worker(platform):
    run_id, report = _drive_pipeline(
        platform, "autonomous_research", "Autonomous exploration topic?"
    )
    assert report["report_markdown"]
    detail = platform[0].get(f"/api/v1/research/{run_id}").json()
    assert detail["status"] == "completed"
