"""Embedding model adapters and registry.

Providers: OpenAI (compatible), Ollama, and a deterministic HashEmbeddings
fallback for offline tests.
"""

from __future__ import annotations

import hashlib
import math
import struct
from typing import Callable, Optional

import httpx
from synthora.core.ports import EmbeddingModel

EmbeddingFactory = Callable[[str], EmbeddingModel]


def _env(*names: str, default: str = "") -> str:
    from synthora.adapters.provider_settings_context import resolve_credential

    return resolve_credential(*names, default=default)


class OpenAIEmbeddings:
    """OpenAI (or compatible) ``/embeddings`` endpoint."""

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self.api_key = api_key or _env("OPENAI_API_KEY")
        self.base_url = (
            base_url
            or _env("OPENAI_BASE_URL", default="https://api.openai.com/v1")
        ).rstrip("/")
        self.timeout = timeout

    def embed_one(self, text: str) -> list[float]:
        """Sync single-text embed for SimilarityFn / knowledge-map paths."""
        vectors = self._embed_sync([text])
        return vectors[0] if vectors else []

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/embeddings",
                json={"model": self.model, "input": texts},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        items = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
        return [list(item.get("embedding") or []) for item in items]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/embeddings",
                json={"model": self.model, "input": texts},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        items = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
        return [list(item.get("embedding") or []) for item in items]


class OllamaEmbeddings:
    """Local Ollama ``/api/embeddings`` (one text per request)."""

    def __init__(
        self,
        model: str = "nomic-embed-text",
        *,
        base_url: Optional[str] = None,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.base_url = (
            base_url or _env("OLLAMA_BASE_URL", default="http://localhost:11434")
        ).rstrip("/")
        self.timeout = timeout

    def embed_one(self, text: str) -> list[float]:
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
            )
            resp.raise_for_status()
            data = resp.json()
        return list(data.get("embedding") or [])

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for text in texts:
                resp = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                )
                resp.raise_for_status()
                data = resp.json()
                vectors.append(list(data.get("embedding") or []))
        return vectors


class HashEmbeddings:
    """Deterministic local bag-of-hashes embedding (offline / tests).

    Same text always yields the same unit-normalized vector of fixed dimension.
    """

    def __init__(self, model: str = "hash", *, dims: int = 64) -> None:
        self.model = model
        self.dims = dims

    def embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dims
        tokens = text.lower().split() or [text]
        for token in tokens:
            digest = hashlib.sha256(f"{self.model}:{token}".encode()).digest()
            # use successive 4-byte chunks as signed floats into dims
            for i in range(0, min(len(digest), self.dims * 4), 4):
                idx = (i // 4) % self.dims
                (val,) = struct.unpack_from(">i", digest, i)
                vec[idx] += float(val % 1000) / 1000.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    # backwards-compatible alias
    _one = embed_one

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(t) for t in texts]


class EmbeddingRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, EmbeddingFactory] = {}

    def register(self, name: str, factory: EmbeddingFactory) -> None:
        self._factories[name] = factory

    def providers(self) -> list[str]:
        return sorted(self._factories)

    def resolve(self, model_id: str) -> EmbeddingModel:
        """Resolve ``provider:model`` (defaults provider to ``openai``)."""
        provider, _, model = model_id.partition(":")
        if not model:
            provider, model = "openai", provider
        if provider not in self._factories:
            raise KeyError(
                f"unknown embedding provider '{provider}' "
                f"(known: {self.providers()})"
            )
        return self._factories[provider](model)


embedding_registry = EmbeddingRegistry()
embedding_registry.register("openai", lambda m: OpenAIEmbeddings(m))
embedding_registry.register("ollama", lambda m: OllamaEmbeddings(m))
embedding_registry.register("hash", lambda m: HashEmbeddings(m))


def resolve_default_embeddings() -> EmbeddingModel:
    """Prefer OpenAI when keyed, else Ollama when base URL set, else hash."""
    forced = _env("SYNTHORA_EMBEDDINGS", default="").strip().lower()
    if forced in ("hash", "offline"):
        return HashEmbeddings()
    if _env("OPENAI_API_KEY"):
        return OpenAIEmbeddings()
    if _env("OLLAMA_BASE_URL") or _env("OLLAMA_EMBED_MODEL"):
        model = _env("OLLAMA_EMBED_MODEL", default="nomic-embed-text")
        return OllamaEmbeddings(model)
    return HashEmbeddings()
