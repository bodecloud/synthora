"""Default embedding resolution for compose and offline dev."""

from __future__ import annotations

from synthora.adapters.embeddings import (
    HashEmbeddings,
    OllamaEmbeddings,
    OpenAIEmbeddings,
    resolve_default_embeddings,
)


def test_resolve_default_embeddings_uses_hash_without_keys(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_EMBED_MODEL", raising=False)
    monkeypatch.delenv("SYNTHORA_EMBEDDINGS", raising=False)
    assert isinstance(resolve_default_embeddings(), HashEmbeddings)


def test_resolve_default_embeddings_forced_hash(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("SYNTHORA_EMBEDDINGS", "hash")
    assert isinstance(resolve_default_embeddings(), HashEmbeddings)


def test_resolve_default_embeddings_prefers_openai_when_keyed(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("SYNTHORA_EMBEDDINGS", raising=False)
    assert isinstance(resolve_default_embeddings(), OpenAIEmbeddings)


def test_resolve_default_embeddings_uses_ollama_when_configured(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SYNTHORA_EMBEDDINGS", raising=False)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    assert isinstance(resolve_default_embeddings(), OllamaEmbeddings)
