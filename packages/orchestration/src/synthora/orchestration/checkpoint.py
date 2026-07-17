"""Shared LangGraph checkpointer for interrupt/resume across pipelines."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger("synthora.orchestration.checkpoint")

# Process-wide checkpointer. Postgres uses AsyncPostgresSaver because graphs
# are invoked via ``ainvoke``; the sync PostgresSaver's async methods raise
# bare NotImplementedError.
_checkpointer: Optional[Any] = None
_postgres_cm: Optional[Any] = None


def _normalize_postgres_url(url: str) -> str:
    """Strip SQLAlchemy dialect prefixes for psycopg connection strings."""
    for prefix in (
        "postgresql+asyncpg://",
        "postgres+asyncpg://",
        "postgresql+psycopg://",
        "postgres+psycopg://",
    ):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    return url


def _backend() -> str:
    return os.environ.get("SYNTHORA_CHECKPOINT_BACKEND", "memory").lower()


def get_checkpointer() -> Any:
    """Return the process-wide checkpointer.

    Default is an in-memory saver (correct for single-worker and tests).
    For ``SYNTHORA_CHECKPOINT_BACKEND=postgres``, call
    ``await ensure_checkpointer()`` once during process startup before
    compiling/invoking graphs (AsyncPostgresSaver is required for ainvoke).
    """
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer
    backend = _backend()
    if backend in ("", "memory", "mem"):
        _checkpointer = MemorySaver()
        return _checkpointer
    if backend != "postgres":
        raise RuntimeError(
            f"Unknown SYNTHORA_CHECKPOINT_BACKEND={backend!r} "
            "(expected 'memory' or 'postgres')"
        )
    raise RuntimeError(
        "Postgres checkpointer not initialized; call "
        "await ensure_checkpointer() during API/worker startup"
    )


async def ensure_checkpointer() -> Any:
    """Initialize the process checkpointer (idempotent).

    Must be awaited before compiling graphs when using the postgres backend.
    """
    global _checkpointer, _postgres_cm
    if _checkpointer is not None:
        return _checkpointer

    backend = _backend()
    if backend in ("", "memory", "mem"):
        _checkpointer = MemorySaver()
        return _checkpointer
    if backend != "postgres":
        raise RuntimeError(
            f"Unknown SYNTHORA_CHECKPOINT_BACKEND={backend!r} "
            "(expected 'memory' or 'postgres')"
        )

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ImportError as exc:  # pragma: no cover - optional dep
        raise RuntimeError(
            "langgraph-checkpoint-postgres is required when "
            "SYNTHORA_CHECKPOINT_BACKEND=postgres"
        ) from exc

    url = (
        os.environ.get("SYNTHORA_CHECKPOINT_URL")
        or os.environ.get("SYNTHORA_DATABASE_URL")
        or os.environ.get("DATABASE_URL", "")
    )
    if not url:
        raise RuntimeError(
            "SYNTHORA_CHECKPOINT_URL (or DATABASE_URL) required "
            "for postgres checkpointer"
        )
    url = _normalize_postgres_url(url)
    cm = AsyncPostgresSaver.from_conn_string(url)
    saver = await cm.__aenter__()
    await saver.setup()
    _postgres_cm = cm
    _checkpointer = saver
    logger.info("Async Postgres checkpointer ready")
    return saver


def reset_checkpointer() -> None:
    """Clear the cached checkpointer (tests only)."""
    global _checkpointer, _postgres_cm
    if _postgres_cm is not None:
        try:
            # Best-effort sync close; tests typically use MemorySaver.
            close = getattr(_postgres_cm, "__aexit__", None)
            if close is not None:
                import asyncio

                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(close(None, None, None))
                    else:
                        loop.run_until_complete(close(None, None, None))
                except Exception:  # noqa: BLE001
                    pass
            else:
                _postgres_cm.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass
        _postgres_cm = None
    _checkpointer = None
