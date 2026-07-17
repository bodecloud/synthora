"""Embedding helpers for knowledge-map / retrieval similarity.

Prefers ``synthora.adapters.embeddings.HashEmbeddings`` when the adapters
package is importable; otherwise falls back to a local deterministic
bag-of-hashes implementation. Produces a sync ``SimilarityFn`` suitable for
``KnowledgeMap`` / discourse ranking.
"""

from __future__ import annotations

import hashlib
import math
import struct
from typing import Callable, Optional

from synthora.intelligence.knowledge_map import SimilarityFn

try:
    from synthora.adapters.embeddings import HashEmbeddings as _AdapterHashEmbeddings
except ImportError:  # pragma: no cover - adapters always present in workspace
    _AdapterHashEmbeddings = None  # type: ignore[misc, assignment]


class HashEmbeddings:
    """Deterministic local bag-of-hashes embedding (offline / tests)."""

    def __init__(self, model: str = "hash", *, dims: int = 64) -> None:
        self.model = model
        self.dims = dims

    def embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dims
        tokens = text.lower().split() or [text]
        for token in tokens:
            digest = hashlib.sha256(f"{self.model}:{token}".encode()).digest()
            for i in range(0, min(len(digest), self.dims * 4), 4):
                idx = (i // 4) % self.dims
                (val,) = struct.unpack_from(">i", digest, i)
                vec[idx] += float(val % 1000) / 1000.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(t) for t in texts]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _sync_encode(embedder: object) -> Callable[[str], list[float]]:
    if hasattr(embedder, "embed_one"):
        return embedder.embed_one  # type: ignore[return-value]
    if hasattr(embedder, "_one"):
        return embedder._one  # type: ignore[return-value]
    raise TypeError(
        f"embedder {type(embedder)!r} needs sync embed_one/_one for SimilarityFn"
    )


def make_embedding_similarity(embedder: Optional[object] = None) -> SimilarityFn:
    """Build a sync cosine ``SimilarityFn`` from the preferred embedder."""
    emb = embedder if embedder is not None else resolve_research_embeddings()
    encode = _sync_encode(emb)

    def similarity(a: str, b: str) -> float:
        return cosine_similarity(encode(a), encode(b))

    return similarity


def default_hash_embeddings() -> object:
    """Adapters HashEmbeddings when available, else local implementation."""
    if _AdapterHashEmbeddings is not None:
        return _AdapterHashEmbeddings()
    return HashEmbeddings()


def resolve_research_embeddings() -> object:
    """OpenAI → Ollama → hash for research-loop similarity and section writing."""
    try:
        from synthora.adapters.embeddings import resolve_default_embeddings

        return resolve_default_embeddings()
    except Exception:
        return default_hash_embeddings()
