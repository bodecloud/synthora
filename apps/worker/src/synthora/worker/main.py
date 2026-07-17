"""Worker entrypoint: consumes the research queue with a concurrency cap
(R-LDR-2) and writes a heartbeat file for the container healthcheck."""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib

import redis.asyncio as aioredis
from synthora.persistence import NewsRepository
from synthora.persistence.database import Database
from synthora.worker.executor import RunExecutor
from synthora.worker.queue import RedisJobQueue

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("synthora.worker")

HEARTBEAT = pathlib.Path(os.environ.get("SYNTHORA_HEARTBEAT_FILE", "/tmp/synthora-worker-heartbeat"))


async def heartbeat_loop() -> None:
    while True:
        HEARTBEAT.touch()
        await asyncio.sleep(30)


async def news_poll_loop(db: Database) -> None:
    """Optionally poll due news subscriptions when SYNTHORA_NEWS_POLL=1."""
    from synthora.worker.news import poll_due_subscriptions

    interval = int(os.environ.get("SYNTHORA_NEWS_POLL_INTERVAL", "300"))
    repo = NewsRepository(db)
    while True:
        try:
            n = await poll_due_subscriptions(repo)
            if n:
                logger.info("news poll: fetched %d due subscription(s)", n)
        except Exception:
            logger.exception("news poll failed")
        await asyncio.sleep(max(30, interval))


async def main() -> None:
    database_url = os.environ.get(
        "SYNTHORA_DATABASE_URL", "sqlite+aiosqlite:///./synthora.db"
    )
    redis_url = os.environ.get("SYNTHORA_REDIS_URL", "redis://localhost:6379/0")
    max_concurrent = int(os.environ.get("SYNTHORA_MAX_CONCURRENT_RESEARCHES", "3"))

    db = Database(database_url)
    await db.ensure_schema()
    try:
        from synthora.adapters.document_index import warm_document_index_from_db

        n = await warm_document_index_from_db(db)
        logger.info("document index warmed with %d document(s)", n)
    except Exception:
        logger.exception(
            "document index warm-up failed; collection RAG may be empty until lazy load"
        )
    redis = aioredis.from_url(redis_url)
    queue = RedisJobQueue(redis)
    executor = RunExecutor(db, queue)
    semaphore = asyncio.Semaphore(max_concurrent)
    tasks: set[asyncio.Task] = set()

    asyncio.create_task(heartbeat_loop())
    if os.environ.get("SYNTHORA_NEWS_POLL", "").strip() in ("1", "true", "yes"):
        asyncio.create_task(news_poll_loop(db))
        logger.info("news poll enabled")
    logger.info("worker started (max_concurrent=%d)", max_concurrent)

    async def run_job(job: dict) -> None:
        async with semaphore:
            run_id = job["run_id"]
            resume_value = job.get("resume_value")
            try:
                run = await executor.execute(run_id, resume_value=resume_value)
                logger.info("run %s finished: %s", run_id, run.status.value)
            except Exception:
                logger.exception("run %s crashed", run_id)

    while True:
        job = await queue.dequeue(timeout=5.0)
        if job is None:
            continue
        task = asyncio.create_task(run_job(job))
        tasks.add(task)
        task.add_done_callback(tasks.discard)


if __name__ == "__main__":
    asyncio.run(main())
