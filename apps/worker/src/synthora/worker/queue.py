"""Redis-backed job queue and event bus (R-LDR-2, R-LDR-3).

Keys:
- list  ``synthora:queue``            — pending run ids
- pubsub ``synthora:events:{run_id}`` — live progress events
- key   ``synthora:cancel:{run_id}``  — cancellation flag
- list  ``synthora:steer:{run_id}``   — user steering messages (HITL)
"""

from __future__ import annotations

import json
from typing import Any, Optional

QUEUE_KEY = "synthora:queue"


def events_channel(run_id: str) -> str:
    return f"synthora:events:{run_id}"


def cancel_key(run_id: str) -> str:
    return f"synthora:cancel:{run_id}"


def steer_key(run_id: str) -> str:
    return f"synthora:steer:{run_id}"


class RedisJobQueue:
    """Implements the JobQueue port over redis.asyncio."""

    def __init__(self, redis) -> None:
        self.redis = redis

    async def enqueue(self, run_id: str, payload: dict[str, Any]) -> None:
        await self.redis.rpush(
            QUEUE_KEY, json.dumps({"run_id": run_id, **payload})
        )

    async def dequeue(self, *, timeout: float = 5.0) -> Optional[dict[str, Any]]:
        item = await self.redis.blpop(QUEUE_KEY, timeout=timeout)
        if item is None:
            return None
        _, raw = item
        if isinstance(raw, bytes):
            raw = raw.decode()
        return json.loads(raw)

    async def request_cancel(self, run_id: str) -> None:
        await self.redis.set(cancel_key(run_id), "1", ex=86400)

    async def is_cancelled(self, run_id: str) -> bool:
        return bool(await self.redis.exists(cancel_key(run_id)))

    async def push_steering(self, run_id: str, message: str) -> None:
        await self.redis.rpush(steer_key(run_id), message)

    async def drain_steering(self, run_id: str) -> list[str]:
        messages: list[str] = []
        while True:
            raw = await self.redis.lpop(steer_key(run_id))
            if raw is None:
                break
            messages.append(raw.decode() if isinstance(raw, bytes) else raw)
        return messages

    async def publish_event(self, run_id: str, event: dict[str, Any]) -> None:
        await self.redis.publish(events_channel(run_id), json.dumps(event))
