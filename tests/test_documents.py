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


@pytest.mark.asyncio
async def test_collection_engine_uses_query_embeddings():
    """Cosine path should hit when query tokens overlap but are not a substring."""
    from synthora.adapters.document_index import document_index
    from synthora.adapters.embeddings import HashEmbeddings
    from synthora.adapters.search_engines import CollectionEngine
    from synthora.adapters.workspace_context import set_workspace_id

    document_index.clear()
    ws = "embed-ws"
    set_workspace_id(ws)
    emb = HashEmbeddings()
    text = "alpha beta gamma delta epsilon"
    vector = (await emb.embed([text]))[0]
    document_index.upsert_document(
        ws,
        {
            "id": "doc-1",
            "title": "Tokens",
            "content": text,
            "url": "https://example.com/tokens",
        },
        chunks=[{"text": text, "embedding": vector}],
    )
    engine = CollectionEngine(documents=[])
    # Non-contiguous token query: not a substring of the document text.
    hits = await engine.search("gamma alpha", max_results=3)
    assert hits, "expected cosine hit without substring match"
    assert hits[0].engine == "collection"
    document_index.clear()


def test_document_multipart_upload(docs_client):
    client = docs_client
    files = {"file": ("notes.md", b"# Hello\n\nquantum lattice surgery notes", "text/markdown")}
    resp = client.post("/api/v1/documents/upload", files=files)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["title"] == "notes"
    assert body["chunk_count"] >= 1
    listed = client.get("/api/v1/documents").json()["documents"]
    assert any(d["id"] == body["id"] for d in listed)


def test_document_extract_rejects_unknown_type():
    import pytest
    from synthora.api.document_extract import extract_document_text

    with pytest.raises(ValueError, match="unsupported"):
        extract_document_text("x.bin", b"\x00\x01")
