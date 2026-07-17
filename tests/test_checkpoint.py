"""Checkpointer backend selection tests."""

from __future__ import annotations

import pytest
from synthora.orchestration.checkpoint import (
    _normalize_postgres_url,
    ensure_checkpointer,
    get_checkpointer,
    reset_checkpointer,
)


def test_normalize_postgres_url_strips_asyncpg():
    assert (
        _normalize_postgres_url(
            "postgresql+asyncpg://u:p@host:5432/db"
        )
        == "postgresql://u:p@host:5432/db"
    )


def test_memory_backend_default(monkeypatch):
    monkeypatch.delenv("SYNTHORA_CHECKPOINT_BACKEND", raising=False)
    reset_checkpointer()
    saver = get_checkpointer()
    assert type(saver).__name__ in ("MemorySaver", "InMemorySaver")
    reset_checkpointer()


def test_postgres_get_before_ensure_raises(monkeypatch):
    monkeypatch.setenv("SYNTHORA_CHECKPOINT_BACKEND", "postgres")
    monkeypatch.setenv("SYNTHORA_CHECKPOINT_URL", "postgresql://u:p@localhost/db")
    reset_checkpointer()
    with pytest.raises(RuntimeError, match="ensure_checkpointer"):
        get_checkpointer()
    reset_checkpointer()


@pytest.mark.asyncio
async def test_postgres_backend_requires_url(monkeypatch):
    monkeypatch.setenv("SYNTHORA_CHECKPOINT_BACKEND", "postgres")
    monkeypatch.delenv("SYNTHORA_CHECKPOINT_URL", raising=False)
    monkeypatch.delenv("SYNTHORA_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    reset_checkpointer()
    with pytest.raises(RuntimeError, match="CHECKPOINT_URL|DATABASE_URL"):
        await ensure_checkpointer()
    reset_checkpointer()
