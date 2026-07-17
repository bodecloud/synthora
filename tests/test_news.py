"""News subscriptions and items API."""

from __future__ import annotations

from synthora.adapters import search_engine_registry
from synthora.core.models import SearchResult

from tests.conftest import FakeSearchEngine

pytest_plugins = ("tests.test_platform",)

def test_news_subscription_crud_and_fetch(platform):
    client, _ = platform

    class NewsFake(FakeSearchEngine):
        async def search(self, query: str, *, max_results: int = 5):
            self.queries.append(query)
            return [
                SearchResult(
                    url="https://news.example/ai",
                    title="AI headline",
                    snippet="About AI regulation",
                    content="About AI regulation",
                    engine="fake",
                    score=1.0,
                )
            ][:max_results]

    search_engine_registry.register("searxng", NewsFake)
    search_engine_registry.register("ddg", NewsFake)
    search_engine_registry.register("null", NewsFake)

    created = client.post(
        "/api/v1/news/subscriptions",
        json={"query": "AI regulation", "cadence": "daily"},
    )
    assert created.status_code == 201
    sub = created.json()
    assert sub["query"] == "AI regulation"
    assert sub["cadence"] == "daily"
    sub_id = sub["id"]

    listed = client.get("/api/v1/news/subscriptions").json()["subscriptions"]
    assert any(s["id"] == sub_id for s in listed)

    patched = client.patch(
        f"/api/v1/news/subscriptions/{sub_id}",
        json={"cadence": "hourly"},
    )
    assert patched.status_code == 200
    assert patched.json()["cadence"] == "hourly"

    fetched = client.post(f"/api/v1/news/subscriptions/{sub_id}/fetch")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["fetched"] >= 1
    assert body["items"][0]["title"] == "AI headline"
    assert body["items"][0]["url"] == "https://news.example/ai"

    items = client.get("/api/v1/news/items").json()["items"]
    assert any(i["title"] == "AI headline" for i in items)

    filtered = client.get(
        f"/api/v1/news/items?subscription_id={sub_id}"
    ).json()["items"]
    assert len(filtered) >= 1

    deleted = client.delete(f"/api/v1/news/subscriptions/{sub_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert (
        client.get(f"/api/v1/news/subscriptions/{sub_id}").status_code == 404
    )


def test_news_bad_cadence_rejected(platform):
    client, _ = platform
    resp = client.post(
        "/api/v1/news/subscriptions",
        json={"query": "x", "cadence": "monthly"},
    )
    assert resp.status_code == 422
