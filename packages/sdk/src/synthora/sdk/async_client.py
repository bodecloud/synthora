"""Async Python client for the Synthora API."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any, Optional

import httpx


class AsyncSynthoraClient:
    """Async client mirroring :class:`SynthoraClient`."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        *,
        token: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def register(self, username: str, password: str) -> str:
        data = await self._post(
            "/api/v1/auth/register", {"username": username, "password": password}
        )
        self.token = data["token"]
        return self.token

    async def login(self, username: str, password: str) -> str:
        data = await self._post(
            "/api/v1/auth/login", {"username": username, "password": password}
        )
        self.token = data["token"]
        return self.token

    async def create_session(
        self, title: str = "Untitled research", tags: Optional[list[str]] = None
    ) -> dict:
        return await self._post("/api/v1/sessions", {"title": title, "tags": tags or []})

    async def list_sessions(self) -> list[dict]:
        return (await self._get("/api/v1/sessions"))["sessions"]

    async def get_session(self, session_id: str) -> dict:
        return await self._get(f"/api/v1/sessions/{session_id}")

    async def delete_session(self, session_id: str) -> dict:
        return await self._delete(f"/api/v1/sessions/{session_id}")

    async def start_research(
        self,
        question: str,
        *,
        pipeline_id: str = "deep_research",
        session_id: Optional[str] = None,
        config: Optional[dict[str, Any]] = None,
    ) -> str:
        body: dict[str, Any] = {
            "question": question,
            "pipeline_id": pipeline_id,
            "config": config,
        }
        if session_id:
            body["session_id"] = session_id
        data = await self._post("/api/v1/research", body)
        return data["run_id"]

    async def get_run(self, run_id: str) -> dict:
        return await self._get(f"/api/v1/research/{run_id}")

    async def list_runs(self, *, session_id: Optional[str] = None) -> list[dict]:
        path = "/api/v1/research"
        if session_id:
            path = f"{path}?session_id={session_id}"
        return (await self._get(path))["runs"]

    async def delete_run(self, run_id: str) -> dict:
        return await self._delete(f"/api/v1/research/{run_id}")

    async def clear_history(self) -> dict:
        return await self._post("/api/v1/research/clear", {})

    async def cancel(self, run_id: str) -> dict:
        return await self._post(f"/api/v1/research/{run_id}/cancel", {})

    async def resume(self, run_id: str, answer: str) -> dict:
        return await self._post(
            f"/api/v1/research/{run_id}/resume", {"answer": answer}
        )

    async def steer(self, run_id: str, message: str) -> dict:
        return await self._post(
            f"/api/v1/research/{run_id}/steer", {"message": message}
        )

    async def get_report(self, run_id: str) -> dict:
        return await self._get(f"/api/v1/research/{run_id}/report")

    async def get_events(self, run_id: str) -> list[dict]:
        return (await self._get(f"/api/v1/research/{run_id}/events"))["events"]

    async def get_knowledge_map(self, run_id: str) -> dict:
        return await self._get(f"/api/v1/research/{run_id}/knowledge-map")

    async def get_discourse(self, run_id: str) -> list[dict]:
        return (await self._get(f"/api/v1/research/{run_id}/discourse"))["turns"]

    def export_url(self, run_id: str, fmt: str = "markdown") -> str:
        return f"{self.base_url}/api/v1/research/{run_id}/export?format={fmt}"

    def events_ws_url(self, run_id: str) -> str:
        ws_base = self.base_url.replace("https://", "wss://").replace(
            "http://", "ws://"
        )
        suffix = f"?token={self.token}" if self.token else ""
        return f"{ws_base}/api/v1/research/{run_id}/events/ws{suffix}"

    async def download_export(self, run_id: str, fmt: str = "markdown") -> bytes:
        resp = await self._client.get(
            f"/api/v1/research/{run_id}/export",
            params={"format": fmt},
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.content

    async def list_pipelines(self) -> list[dict]:
        return (await self._get("/api/v1/pipelines"))["pipelines"]

    async def list_providers(self) -> dict:
        return await self._get("/api/v1/providers")

    async def wait_for_report(
        self, run_id: str, *, poll_seconds: float = 2.0, timeout: float = 1800.0
    ) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            run = await self.get_run(run_id)
            status = run["status"]
            if status == "completed":
                return await self.get_report(run_id)
            if status == "awaiting_input":
                raise RuntimeError(
                    f"run {run_id} is awaiting_input; call resume() with an answer"
                )
            if status in ("failed", "cancelled"):
                raise RuntimeError(
                    f"run {run_id} {status}: {run.get('error')}"
                )
            await asyncio.sleep(poll_seconds)
        raise TimeoutError(f"run {run_id} did not finish within {timeout}s")

    async def iter_run_events(self, run_id: str) -> AsyncIterator[dict]:
        """Stream live events from the run WebSocket."""
        import websockets

        url = self.events_ws_url(run_id)
        headers = []
        if self.token:
            headers.append(("Authorization", f"Bearer {self.token}"))
        async with websockets.connect(url, additional_headers=headers) as ws:
            while True:
                raw = await ws.recv()
                yield json.loads(raw)

    async def chat(self, message: str, *, session_id: Optional[str] = None) -> dict:
        body: dict[str, Any] = {"message": message}
        if session_id:
            body["session_id"] = session_id
        return await self._post("/api/v1/chat", body)

    async def followup(
        self, run_id: str, question: str, *, pipeline_id: Optional[str] = None
    ) -> dict:
        body: dict[str, Any] = {"question": question}
        if pipeline_id:
            body["pipeline_id"] = pipeline_id
        return await self._post(f"/api/v1/research/{run_id}/followup", body)

    async def list_documents(self) -> list[dict]:
        return (await self._get("/api/v1/documents"))["documents"]

    async def create_document(
        self, title: str, content: str, *, url: Optional[str] = None
    ) -> dict:
        body: dict[str, Any] = {"title": title, "content": content}
        if url:
            body["url"] = url
        return await self._post("/api/v1/documents", body)

    async def upload_document(
        self,
        file: str | bytes,
        *,
        filename: str = "upload.txt",
        title: Optional[str] = None,
    ) -> dict:
        if isinstance(file, str):
            with open(file, "rb") as handle:
                payload = handle.read()
            filename = filename or file.rsplit("/", 1)[-1]
        else:
            payload = file
        files = {"file": (filename, payload, "application/octet-stream")}
        data: dict[str, str] = {}
        if title:
            data["title"] = title
        resp = await self._client.post(
            "/api/v1/documents/upload",
            files=files,
            data=data or None,
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def delete_document(self, document_id: str) -> dict:
        return await self._delete(f"/api/v1/documents/{document_id}")

    async def search_documents(
        self, query: str, *, max_results: int = 5
    ) -> list[dict]:
        return (
            await self._post(
                "/api/v1/documents/search",
                {"query": query, "max_results": max_results},
            )
        ).get("results", [])

    async def list_news_subscriptions(self) -> list[dict]:
        return (await self._get("/api/v1/news/subscriptions"))["subscriptions"]

    async def get_news_subscription(self, subscription_id: str) -> dict:
        return await self._get(f"/api/v1/news/subscriptions/{subscription_id}")

    async def create_news_subscription(
        self, query: str, *, cadence: str = "daily"
    ) -> dict:
        return await self._post(
            "/api/v1/news/subscriptions", {"query": query, "cadence": cadence}
        )

    async def delete_news_subscription(self, subscription_id: str) -> dict:
        return await self._delete(f"/api/v1/news/subscriptions/{subscription_id}")

    async def fetch_news_subscription(self, subscription_id: str) -> dict:
        return await self._post(
            f"/api/v1/news/subscriptions/{subscription_id}/fetch", {}
        )

    async def update_news_subscription(
        self,
        subscription_id: str,
        *,
        query: Optional[str] = None,
        cadence: Optional[str] = None,
    ) -> dict:
        body: dict[str, Any] = {}
        if query is not None:
            body["query"] = query
        if cadence is not None:
            body["cadence"] = cadence
        return await self._patch(
            f"/api/v1/news/subscriptions/{subscription_id}", body
        )

    async def list_news_items(
        self, *, subscription_id: Optional[str] = None
    ) -> list[dict]:
        path = "/api/v1/news/items"
        if subscription_id:
            path = f"{path}?subscription_id={subscription_id}"
        return (await self._get(path))["items"]

    async def list_settings(self) -> list[dict]:
        return (await self._get("/api/v1/settings"))["settings"]

    async def get_setting(self, key: str) -> dict:
        return await self._get(f"/api/v1/settings/{key}")

    async def put_setting(self, key: str, value: dict[str, Any]) -> dict:
        return await self._put(f"/api/v1/settings/{key}", {"value": value})

    async def get_run_metrics(self, run_id: str) -> dict:
        return await self._get(f"/api/v1/research/{run_id}/metrics")

    async def metrics_summary(self) -> dict:
        return await self._get("/api/v1/metrics/summary")

    async def mcp_tools_list(self) -> dict:
        return await self._post("/api/v1/mcp/tools/list", {})

    async def mcp_tools_call(
        self, name: str, arguments: Optional[dict] = None
    ) -> dict:
        return await self._post(
            "/api/v1/mcp/tools/call",
            {"name": name, "arguments": arguments or {}},
        )

    async def health(self) -> dict:
        return await self._get("/health")

    async def ready(self) -> dict:
        return await self._get("/ready")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    async def _get(self, path: str) -> dict:
        resp = await self._client.get(path, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, body: dict) -> dict:
        resp = await self._client.post(path, json=body, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    async def _put(self, path: str, body: dict) -> dict:
        resp = await self._client.put(path, json=body, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    async def _patch(self, path: str, body: dict) -> dict:
        resp = await self._client.patch(path, json=body, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    async def _delete(self, path: str) -> dict:
        resp = await self._client.delete(path, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AsyncSynthoraClient:
        return self

    async def __aexit__(self, *args) -> None:
        await self.aclose()
