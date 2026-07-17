"""In-process document index for the ``collection`` search engine.

The API upserts workspace documents (and chunk embeddings) here after persist
so researchers that include ``collection`` in ``search_engines`` can retrieve
library content without a DB round-trip in the engine adapter.
"""

from __future__ import annotations

import math
from threading import Lock
from typing import Optional

from synthora.core.models import SearchResult


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(dot / (na * nb))


class DocumentIndex:
    """Thread-safe workspace-keyed document + chunk registry."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._docs: dict[str, dict[str, dict]] = {}
        self._chunks: dict[str, list[dict]] = {}

    def upsert(self, workspace_id: str, document: dict) -> None:
        doc_id = str(document.get("id") or "")
        if not doc_id:
            raise ValueError("document id required")
        with self._lock:
            bucket = self._docs.setdefault(workspace_id, {})
            bucket[doc_id] = {
                "id": doc_id,
                "title": document.get("title") or "",
                "url": document.get("url") or f"collection://{doc_id}",
                "content": document.get("content")
                or document.get("text")
                or "",
                "workspace_id": workspace_id,
            }

    def upsert_document(
        self,
        workspace_id: str,
        document: dict,
        chunks: Optional[list[dict]] = None,
    ) -> None:
        """Upsert a document and optionally replace its chunk embeddings."""
        self.upsert(workspace_id, document)
        doc_id = str(document.get("id") or "")
        if chunks is not None and doc_id:
            self.upsert_chunks(
                workspace_id,
                doc_id,
                chunks,
                title=str(document.get("title") or ""),
                url=str(document.get("url") or f"collection://{doc_id}"),
            )

    def upsert_chunks(
        self,
        workspace_id: str,
        document_id: str,
        chunks: list[dict],
        *,
        title: str = "",
        url: str = "",
    ) -> None:
        """Replace in-memory chunks for one document."""
        prepared = []
        for i, chunk in enumerate(chunks):
            prepared.append(
                {
                    "document_id": document_id,
                    "chunk_index": int(chunk.get("chunk_index", i)),
                    "text": str(chunk.get("text") or ""),
                    "embedding": list(chunk.get("embedding") or []),
                    "title": title or str(chunk.get("title") or ""),
                    "url": url
                    or str(chunk.get("url") or f"collection://{document_id}"),
                }
            )
        with self._lock:
            existing = [
                c
                for c in (self._chunks.get(workspace_id) or [])
                if c.get("document_id") != document_id
            ]
            existing.extend(prepared)
            self._chunks[workspace_id] = existing

    def remove(self, workspace_id: str, document_id: str) -> bool:
        with self._lock:
            bucket = self._docs.get(workspace_id) or {}
            existed = document_id in bucket
            if existed:
                del bucket[document_id]
                if not bucket:
                    self._docs.pop(workspace_id, None)
            chunks = self._chunks.get(workspace_id) or []
            kept = [c for c in chunks if c.get("document_id") != document_id]
            if kept:
                self._chunks[workspace_id] = kept
            else:
                self._chunks.pop(workspace_id, None)
            return existed

    def documents(self, workspace_id: Optional[str] = None) -> list[dict]:
        with self._lock:
            if workspace_id is not None:
                return list((self._docs.get(workspace_id) or {}).values())
            out: list[dict] = []
            for bucket in self._docs.values():
                out.extend(bucket.values())
            return out

    def clear(self, workspace_id: Optional[str] = None) -> None:
        with self._lock:
            if workspace_id is None:
                self._docs.clear()
                self._chunks.clear()
            else:
                self._docs.pop(workspace_id, None)
                self._chunks.pop(workspace_id, None)

    def search(
        self,
        workspace_id: str,
        query: str,
        *,
        query_embedding: Optional[list[float]] = None,
        max_results: int = 5,
    ) -> list[SearchResult]:
        q = (query or "").lower().strip()
        with self._lock:
            chunks = list(self._chunks.get(workspace_id) or [])
            docs = dict(self._docs.get(workspace_id) or {})

        scored: list[tuple[float, dict]] = []
        for chunk in chunks:
            score = 0.0
            emb = chunk.get("embedding") or []
            if query_embedding and emb:
                score = _cosine(query_embedding, emb)
            text = str(chunk.get("text") or "")
            title = str(chunk.get("title") or "")
            if q:
                hay = f"{title}\n{text}".lower()
                if q in hay:
                    score = max(score, 0.85 if q in title.lower() else 0.55)
            if score > 0:
                scored.append((score, chunk))

        # Fall back to full-document substring match when no chunks scored.
        if not scored and q:
            for doc in docs.values():
                title = str(doc.get("title") or "")
                content = str(doc.get("content") or "")
                hay = f"{title}\n{content}".lower()
                if q in hay:
                    scored.append(
                        (
                            1.0 if q in title.lower() else 0.5,
                            {
                                "document_id": doc.get("id"),
                                "text": content,
                                "title": title,
                                "url": doc.get("url"),
                            },
                        )
                    )

        scored.sort(key=lambda t: t[0], reverse=True)
        results: list[SearchResult] = []
        for score, chunk in scored[:max_results]:
            text = str(chunk.get("text") or "")
            results.append(
                SearchResult(
                    url=str(
                        chunk.get("url")
                        or f"collection://{chunk.get('document_id', 'doc')}"
                    ),
                    title=str(chunk.get("title") or ""),
                    snippet=text[:500],
                    content=text,
                    engine="collection",
                    score=float(score),
                    metadata={
                        "document_id": chunk.get("document_id"),
                        "chunk_index": chunk.get("chunk_index"),
                    },
                )
            )
        return results


document_index = DocumentIndex()


async def warm_document_index_from_db(db: object) -> int:
    """Load all persisted documents + chunks into the in-process index.

    Shared by the API lifespan and the worker so ``collection`` RAG works
    across processes (compose runs api and worker separately).
    """
    from synthora.persistence.repositories import DocumentRepository

    document_index.clear()
    repo = DocumentRepository(db)  # type: ignore[arg-type]
    docs = await repo.list_all_documents()
    for doc in docs:
        document_index.upsert(
            doc.workspace_id,
            {
                "id": doc.id,
                "title": doc.title,
                "url": doc.url,
                "content": doc.content,
            },
        )
        chunks = await repo.list_chunks(
            workspace_id=doc.workspace_id, document_id=doc.id
        )
        if chunks:
            document_index.upsert_chunks(
                doc.workspace_id,
                doc.id,
                [
                    {
                        "chunk_index": c.chunk_index,
                        "text": c.text,
                        "embedding": c.embedding,
                    }
                    for c in chunks
                ],
                title=doc.title,
                url=doc.url or f"collection://{doc.id}",
            )
    return len(docs)


async def ensure_workspace_index(workspace_id: str, db: object) -> None:
    """Lazy-load one workspace into the index when the worker missed warm-up."""
    if document_index.documents(workspace_id):
        return
    from synthora.persistence.repositories import DocumentRepository

    repo = DocumentRepository(db)  # type: ignore[arg-type]
    docs = await repo.list_documents(workspace_id)
    for doc in docs:
        document_index.upsert(
            workspace_id,
            {
                "id": doc.id,
                "title": doc.title,
                "url": doc.url,
                "content": doc.content,
            },
        )
        chunks = await repo.list_chunks(
            workspace_id=workspace_id, document_id=doc.id
        )
        if chunks:
            document_index.upsert_chunks(
                workspace_id,
                doc.id,
                [
                    {
                        "chunk_index": c.chunk_index,
                        "text": c.text,
                        "embedding": c.embedding,
                    }
                    for c in chunks
                ],
                title=doc.title,
                url=doc.url or f"collection://{doc.id}",
            )
