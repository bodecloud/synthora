"""Document library + RAG API (offline HashEmbeddings)."""

from __future__ import annotations

import fakeredis.aioredis
import pytest
import synthora.api.main as api_main
from fastapi.testclient import TestClient
from synthora.adapters.document_index import document_index
from synthora.adapters.search_engines import CollectionEngine
from synthora.api.settings import settings


@pytest.fixture
def docs_client(tmp_path, monkeypatch):
    settings.database_url = f"sqlite+aiosqlite:///{tmp_path}/docs.db"
    settings.auth_mode = "none"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    fake_redis = fakeredis.aioredis.FakeRedis()
    monkeypatch.setattr(api_main.aioredis, "from_url", lambda url: fake_redis)
    document_index.clear()
    with TestClient(api_main.app) as client:
        yield client
    document_index.clear()


def test_document_crud_and_search(docs_client):
    client = docs_client
    # long enough to force multiple ~500-char chunks
    content = ("quantum error correction surface code " * 40).strip()
    created = client.post(
        "/api/v1/documents",
        json={
            "title": "QEC notes",
            "content": content,
            "url": "https://example.com/qec",
        },
    )
    assert created.status_code == 201
    body = created.json()
    doc_id = body["id"]
    assert body["chunk_count"] >= 2

    listed = client.get("/api/v1/documents").json()["documents"]
    assert any(d["id"] == doc_id for d in listed)

    search = client.post(
        "/api/v1/documents/search",
        json={"query": "quantum error correction", "max_results": 3},
    )
    assert search.status_code == 200
    results = search.json()["results"]
    assert results
    assert results[0]["score"] > 0

    # collection engine reads DocumentIndex
    engine = CollectionEngine()

    async def _search():
        return await engine.search("quantum error correction", max_results=3)

    hits = client.portal.call(_search)
    assert hits
    assert hits[0].engine == "collection"

    deleted = client.delete(f"/api/v1/documents/{doc_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert client.get("/api/v1/documents").json()["documents"] == []


def test_document_search_empty_query_rejected(docs_client):
    client = docs_client
    resp = client.post("/api/v1/documents/search", json={"query": ""})
    assert resp.status_code == 422
