"""Process-local db/queue handles for MCP tool execution."""

from __future__ import annotations

from typing import Optional

from synthora.persistence.database import Database
from synthora.worker.queue import RedisJobQueue

_db: Optional[Database] = None
_queue: Optional[RedisJobQueue] = None


def bind_mcp_runtime(db: Database, queue: RedisJobQueue) -> None:
    global _db, _queue
    _db = db
    _queue = queue


def get_mcp_runtime() -> tuple[Database, RedisJobQueue]:
    if _db is None or _queue is None:
        raise RuntimeError("MCP runtime not initialized")
    return _db, _queue
