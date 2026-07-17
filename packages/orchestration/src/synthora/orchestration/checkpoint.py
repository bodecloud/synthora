"""Shared LangGraph checkpointer for interrupt/resume across pipelines."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any, Optional

from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger("synthora.orchestration.checkpoint")

# Keep Postgres context managers alive for the process lifetime.
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


@lru_cache(maxsize=1)
def get_checkpointer() -> Any:
    """Return the process-wide checkpointer.

    Default is an in-memory saver (correct for single-worker and tests).
    Set ``SYNTHORA_CHECKPOINT_BACKEND=postgres`` and
    ``SYNTHORA_CHECKPOINT_URL`` (or ``DATABASE_URL`` / ``SYNTHORA_DATABASE_URL``)
    to use Postgres when multi-worker resume is required.

    When postgres is requested, initialization failures raise — they no longer
    silently fall back to MemorySaver (which breaks cross-process resume).
    """
    global _postgres_cm
    backend = os.environ.get("SYNTHORA_CHECKPOINT_BACKEND", "memory").lower()
    if backend in ("", "memory", "mem"):
        return MemorySaver()
    if backend != "postgres":
        raise RuntimeError(
            f"Unknown SYNTHORA_CHECKPOINT_BACKEND={backend!r} "
            "(expected 'memory' or 'postgres')"
        )

    try:
        from langgraph.checkpoint.postgres import PostgresSaver
    except ImportError as exc:  # pragma: no cover - optional dep
        raise RuntimeError(
            "langgraph-checkpoint-postgres is required when "
            "SYNTHORA_CHECKPOINT_BACKEND=postgres"
        ) from exc

    url = os.environ.get("SYNTHORA_CHECKPOINT_URL") or os.environ.get(
        "SYNTHORA_DATABASE_URL"
    ) or os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "SYNTHORA_CHECKPOINT_URL (or DATABASE_URL) required "
            "for postgres checkpointer"
        )
    url = _normalize_postgres_url(url)
    # from_conn_string is a context manager — enter once and retain for life.
    cm = PostgresSaver.from_conn_string(url)
    saver = cm.__enter__()
    saver.setup()
    _postgres_cm = cm
    logger.info("Postgres checkpointer ready")
    return saver


def reset_checkpointer() -> None:
    """Clear the cached checkpointer (tests only)."""
    global _postgres_cm
    if _postgres_cm is not None:
        try:
            _postgres_cm.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass
        _postgres_cm = None
    get_checkpointer.cache_clear()
