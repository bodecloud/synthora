"""Python client for the Synthora API (R-LDR-8)."""

from __future__ import annotations

import time
from typing import Any, Optional

import httpx


class SynthoraClient:
    """Synchronous client mirroring the REST API.

    Example:
        client = SynthoraClient("http://localhost:8000")
        run_id = client.start_research("What is X?", pipeline_id="fast_research")
        report = client.wait_for_report(run_id)
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        *,
        token: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    # -- auth ----------------------------------------------------------------

    def register(self, username: str, password: str) -> str:
        data = self._post("/api/v1/auth/register", {"username": username, "password": password})
        self.token = data["token"]
        return self.token

    def login(self, username: str, password: str) -> str:
        data = self._post("/api/v1/auth/login", {"username": username, "password": password})
        self.token = data["token"]
        return self.token

    # -- sessions ------------------------------------------------------------

    def create_session(self, title: str = "Untitled research", tags: Optional[list[str]] = None) -> dict:
        return self._post("/api/v1/sessions", {"title": title, "tags": tags or []})

    def list_sessions(self) -> list[dict]:
        return self._get("/api/v1/sessions")["sessions"]

    def get_session(self, session_id: str) -> dict:
        return self._get(f"/api/v1/sessions/{session_id}")

    def delete_session(self, session_id: str) -> dict:
        return self._delete(f"/api/v1/sessions/{session_id}")

    # -- research ------------------------------------------------------------

    def start_research(
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
        data = self._post("/api/v1/research", body)
        return data["run_id"]

    def get_run(self, run_id: str) -> dict:
        return self._get(f"/api/v1/research/{run_id}")

    def list_runs(self, *, session_id: Optional[str] = None) -> list[dict]:
        path = "/api/v1/research"
        if session_id:
            path = f"{path}?session_id={session_id}"
        return self._get(path)["runs"]

    def delete_run(self, run_id: str) -> dict:
        return self._delete(f"/api/v1/research/{run_id}")

    def clear_history(self) -> dict:
        return self._post("/api/v1/research/clear", {})

    def cancel(self, run_id: str) -> dict:
        return self._post(f"/api/v1/research/{run_id}/cancel", {})

    def resume(self, run_id: str, answer: str) -> dict:
        return self._post(f"/api/v1/research/{run_id}/resume", {"answer": answer})

    def steer(self, run_id: str, message: str) -> dict:
        return self._post(f"/api/v1/research/{run_id}/steer", {"message": message})

    def get_report(self, run_id: str) -> dict:
        return self._get(f"/api/v1/research/{run_id}/report")

    def get_events(self, run_id: str) -> list[dict]:
        return self._get(f"/api/v1/research/{run_id}/events")["events"]

    def get_knowledge_map(self, run_id: str) -> dict:
        return self._get(f"/api/v1/research/{run_id}/knowledge-map")

    def get_discourse(self, run_id: str) -> list[dict]:
        return self._get(f"/api/v1/research/{run_id}/discourse")["turns"]

    def export_url(self, run_id: str, fmt: str = "markdown") -> str:
        return f"{self.base_url}/api/v1/research/{run_id}/export?format={fmt}"

    def download_export(self, run_id: str, fmt: str = "markdown") -> bytes:
        """Download export bytes with auth (session mode safe)."""
        resp = self._client.get(
            f"/api/v1/research/{run_id}/export",
            params={"format": fmt},
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.content

    def list_pipelines(self) -> list[dict]:
        return self._get("/api/v1/pipelines")["pipelines"]

    def list_providers(self) -> dict:
        return self._get("/api/v1/providers")

    def wait_for_report(
        self, run_id: str, *, poll_seconds: float = 2.0, timeout: float = 1800.0
    ) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            run = self.get_run(run_id)
            status = run["status"]
            if status == "completed":
                return self.get_report(run_id)
            if status == "awaiting_input":
                raise RuntimeError(
                    f"run {run_id} is awaiting_input; call resume() with an answer"
                )
            if status in ("failed", "cancelled"):
                raise RuntimeError(
                    f"run {run_id} {status}: {run.get('error')}"
                )
            time.sleep(poll_seconds)
        raise TimeoutError(f"run {run_id} did not finish within {timeout}s")

    # -- chat / follow-up ----------------------------------------------------

    def chat(self, message: str, *, session_id: Optional[str] = None) -> dict:
        body: dict[str, Any] = {"message": message}
        if session_id:
            body["session_id"] = session_id
        return self._post("/api/v1/chat", body)

    def followup(
        self, run_id: str, question: str, *, pipeline_id: Optional[str] = None
    ) -> dict:
        body: dict[str, Any] = {"question": question}
        if pipeline_id:
            body["pipeline_id"] = pipeline_id
        return self._post(f"/api/v1/research/{run_id}/followup", body)

    # -- documents -----------------------------------------------------------

    def list_documents(self) -> list[dict]:
        return self._get("/api/v1/documents")["documents"]

    def create_document(
        self, title: str, content: str, *, url: Optional[str] = None
    ) -> dict:
        body: dict[str, Any] = {"title": title, "content": content}
        if url:
            body["url"] = url
        return self._post("/api/v1/documents", body)

    def upload_document(
        self,
        file: str | bytes,
        *,
        filename: str = "upload.txt",
        title: Optional[str] = None,
    ) -> dict:
        """Upload a file via multipart ``POST /api/v1/documents/upload``."""
        if isinstance(file, str):
            path = file
            with open(path, "rb") as handle:
                payload = handle.read()
            filename = filename or path.rsplit("/", 1)[-1]
        else:
            payload = file
        files = {"file": (filename, payload, "application/octet-stream")}
        data: dict[str, str] = {}
        if title:
            data["title"] = title
        resp = self._client.post(
            "/api/v1/documents/upload",
            files=files,
            data=data or None,
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def delete_document(self, document_id: str) -> dict:
        return self._delete(f"/api/v1/documents/{document_id}")

    def search_documents(self, query: str, *, max_results: int = 5) -> list[dict]:
        return self._post(
            "/api/v1/documents/search",
            {"query": query, "max_results": max_results},
        ).get("results", [])

    # -- news ----------------------------------------------------------------

    def list_news_subscriptions(self) -> list[dict]:
        return self._get("/api/v1/news/subscriptions")["subscriptions"]

    def get_news_subscription(self, subscription_id: str) -> dict:
        return self._get(f"/api/v1/news/subscriptions/{subscription_id}")

    def create_news_subscription(self, query: str, *, cadence: str = "daily") -> dict:
        return self._post(
            "/api/v1/news/subscriptions", {"query": query, "cadence": cadence}
        )

    def delete_news_subscription(self, subscription_id: str) -> dict:
        return self._delete(f"/api/v1/news/subscriptions/{subscription_id}")

    def fetch_news_subscription(self, subscription_id: str) -> dict:
        return self._post(f"/api/v1/news/subscriptions/{subscription_id}/fetch", {})

    def update_news_subscription(
        self, subscription_id: str, *, query: Optional[str] = None, cadence: Optional[str] = None
    ) -> dict:
        body: dict[str, Any] = {}
        if query is not None:
            body["query"] = query
        if cadence is not None:
            body["cadence"] = cadence
        return self._patch(f"/api/v1/news/subscriptions/{subscription_id}", body)

    def list_news_items(self, *, subscription_id: Optional[str] = None) -> list[dict]:
        path = "/api/v1/news/items"
        if subscription_id:
            path = f"{path}?subscription_id={subscription_id}"
        return self._get(path)["items"]

    # -- settings / metrics / mcp --------------------------------------------

    def list_settings(self) -> list[dict]:
        return self._get("/api/v1/settings")["settings"]

    def get_setting(self, key: str) -> dict:
        return self._get(f"/api/v1/settings/{key}")

    def put_setting(self, key: str, value: dict[str, Any]) -> dict:
        return self._put(f"/api/v1/settings/{key}", {"value": value})

    def get_run_metrics(self, run_id: str) -> dict:
        return self._get(f"/api/v1/research/{run_id}/metrics")

    def metrics_summary(self) -> dict:
        return self._get("/api/v1/metrics/summary")

    def mcp_tools_list(self) -> dict:
        return self._post("/api/v1/mcp/tools/list", {})

    def mcp_tools_call(self, name: str, arguments: Optional[dict] = None) -> dict:
        return self._post(
            "/api/v1/mcp/tools/call",
            {"name": name, "arguments": arguments or {}},
        )

    # -- ops -----------------------------------------------------------------

    def health(self) -> dict:
        return self._get("/health")

    def ready(self) -> dict:
        return self._get("/ready")

    # -- plumbing ----------------------------------------------------------

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _get(self, path: str) -> dict:
        resp = self._client.get(path, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict) -> dict:
        resp = self._client.post(path, json=body, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def _put(self, path: str, body: dict) -> dict:
        resp = self._client.put(path, json=body, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def _patch(self, path: str, body: dict) -> dict:
        resp = self._client.patch(path, json=body, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str) -> dict:
        resp = self._client.delete(path, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        self._client.close()
