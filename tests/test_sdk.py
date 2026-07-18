"""Python SDK coverage against the in-process API (R-LDR-8)."""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx
import pytest
from synthora.sdk.client import SynthoraClient

from tests.test_platform import fake_run_config, make_executor

pytest_plugins = ("tests.test_platform",)


class _TestResponse:
    def __init__(self, response) -> None:
        self._response = response
        self.status_code = response.status_code

    @property
    def content(self) -> bytes:
        return self._response.content

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            self._response.raise_for_status()

    def json(self) -> dict[str, Any]:
        return self._response.json()


class _TestHttpClient:
    """Minimal httpx.Client stand-in backed by FastAPI TestClient."""

    def __init__(self, test_client) -> None:
        self._client = test_client

    def get(
        self,
        path: str,
        *,
        headers: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> _TestResponse:
        return _TestResponse(
            self._client.get(path, headers=headers or {}, params=params or {})
        )

    def post(
        self,
        path: str,
        *,
        json: Optional[dict] = None,
        files: Optional[dict] = None,
        data: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> _TestResponse:
        kwargs: dict[str, Any] = {"headers": headers or {}}
        if files is not None:
            kwargs["files"] = files
            if data:
                kwargs["data"] = data
            return _TestResponse(self._client.post(path, **kwargs))
        return _TestResponse(self._client.post(path, json=json, **kwargs))

    def put(
        self, path: str, *, json: dict, headers: Optional[dict] = None
    ) -> _TestResponse:
        return _TestResponse(
            self._client.put(path, json=json, headers=headers or {})
        )

    def patch(
        self, path: str, *, json: dict, headers: Optional[dict] = None
    ) -> _TestResponse:
        return _TestResponse(
            self._client.patch(path, json=json, headers=headers or {})
        )

    def delete(
        self, path: str, *, headers: Optional[dict] = None
    ) -> _TestResponse:
        return _TestResponse(self._client.delete(path, headers=headers or {}))

    def close(self) -> None:
        return None


@pytest.fixture
def sdk(platform):
    client, _app = platform
    wrapper = SynthoraClient("http://testserver")
    wrapper._client = _TestHttpClient(client)
    yield wrapper


def test_sdk_upload_document(sdk, tmp_path):
    path = tmp_path / "sdk-notes.txt"
    path.write_text("sdk upload quantum notes", encoding="utf-8")
    doc = sdk.upload_document(str(path), title="SDK notes")
    assert doc["id"]
    assert doc["title"] == "SDK notes"
    assert doc["chunk_count"] >= 1
    listed = sdk.list_documents()
    assert any(d["id"] == doc["id"] for d in listed)


def test_sdk_update_news_subscription(sdk):
    sub = sdk.create_news_subscription("ai policy", cadence="daily")
    updated = sdk.update_news_subscription(
        sub["id"], query="eu ai act", cadence="weekly"
    )
    assert updated["query"] == "eu ai act"
    assert updated["cadence"] == "weekly"


def test_sdk_mcp_tools_call(sdk):
    tools = sdk.mcp_tools_list()["tools"]
    names = {t["name"] for t in tools}
    assert "start_research" in names
    start_schema = next(t for t in tools if t["name"] == "start_research")
    assert "config" in start_schema["inputSchema"]["properties"]

    started = sdk.mcp_tools_call(
        "start_research",
        {
            "question": "What is the SDK?",
            "pipeline_id": "fast_research",
            "config": fake_run_config(),
        },
    )
    payload = json.loads(started["content"])
    assert payload["run_id"]
    assert payload["status"] == "queued"


def test_sdk_get_news_subscription(sdk):
    sub = sdk.create_news_subscription("climate tech", cadence="daily")
    fetched = sdk.get_news_subscription(sub["id"])
    assert fetched["id"] == sub["id"]
    assert fetched["query"] == "climate tech"


def test_sdk_search_documents_max_results(sdk):
    sdk.create_document("Alpha", "alpha unique token one two three")
    sdk.create_document("Beta", "beta unique token four five six")
    hits = sdk.search_documents("unique token", max_results=1)
    assert len(hits) == 1


def test_sdk_download_export(platform, sdk):
    client, app = platform
    run_id = client.post(
        "/api/v1/research",
        json={
            "question": "Export via SDK?",
            "pipeline_id": "fast_research",
            "config": fake_run_config(),
        },
    ).json()["run_id"]
    client.portal.call(make_executor(app).execute, run_id)
    markdown = sdk.download_export(run_id, "markdown")
    assert b"Integration Report" in markdown
    html = sdk.download_export(run_id, "html")
    assert b"<" in html


def test_sdk_health_and_ready(sdk):
    assert sdk.health()["status"] == "ok"
    assert sdk.ready()["status"] == "ready"


def test_sync_events_ws_url(sdk):
    sdk.token = "tok"
    url = sdk.events_ws_url("run-1")
    assert "/api/v1/research/run-1/events/ws" in url
    assert "token=tok" in url


def test_sync_iter_run_events(monkeypatch):
    from websockets.exceptions import ConnectionClosedOK

    payloads = [
        {"type": "status", "message": "queued"},
        {"type": "done", "message": "completed"},
    ]

    class _FakeWS:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def recv(self):
            if payloads:
                return json.dumps(payloads.pop(0))
            raise ConnectionClosedOK(None, None)

    monkeypatch.setattr(
        "websockets.sync.client.connect",
        lambda *_a, **_k: _FakeWS(),
    )
    client = SynthoraClient("http://localhost:8000")
    events = list(client.iter_run_events("run-1"))
    assert events[0]["type"] == "status"
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_async_sdk_health_and_mcp(platform):
    from httpx import ASGITransport
    from synthora.sdk.async_client import AsyncSynthoraClient

    _client, app = platform
    async with AsyncSynthoraClient("http://testserver") as sdk:
        sdk._client = httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        )
        assert (await sdk.health())["status"] == "ok"
        tools = await sdk.mcp_tools_list()
        assert {t["name"] for t in tools["tools"]} == {
            "start_research",
            "get_run_status",
            "get_report",
            "search_documents",
        }
