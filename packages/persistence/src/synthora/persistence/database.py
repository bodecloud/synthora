"""Async database engine/session management."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from synthora.persistence.tables import Base

logger = logging.getLogger("synthora.persistence")


def _alembic_upgrade(database_url: str) -> None:
    """Run ``alembic upgrade head`` synchronously (for thread offload)."""
    from alembic import command
    from alembic.config import Config

    # Prefer repo-root alembic.ini (Docker WORKDIR=/app; local: synthora/).
    candidates = [
        Path.cwd() / "alembic.ini",
        Path(__file__).resolve().parents[4] / "alembic.ini",
        Path("/app/alembic.ini"),
    ]
    ini = next((p for p in candidates if p.is_file()), None)
    if ini is None:
        raise FileNotFoundError(
            "alembic.ini not found (cwd={!r})".format(str(Path.cwd()))
        )
    cfg = Config(str(ini))
    cfg.set_main_option("sqlalchemy.url", database_url)
    os.environ.setdefault("SYNTHORA_DATABASE_URL", database_url)
    command.upgrade(cfg, "head")


class Database:
    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.url = url
        self.engine: AsyncEngine = create_async_engine(url, echo=echo)
        self.session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )

    async def create_all(self) -> None:
        """Create tables directly (dev/tests). Production prefers Alembic."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def ensure_schema(self) -> None:
        """Bring schema up to date.

        - SQLite / tests: ``create_all`` only.
        - Postgres (default): ``alembic upgrade head``, then ``create_all`` as a
          safety net for any model columns not yet covered by migrations.
        """
        use_alembic = os.environ.get("SYNTHORA_USE_ALEMBIC", "").strip().lower()
        is_sqlite = self.url.startswith("sqlite")
        if is_sqlite or use_alembic in ("0", "false", "no"):
            await self.create_all()
            return
        # Postgres (and other) — prefer Alembic when available.
        if use_alembic in ("1", "true", "yes") or not is_sqlite:
            try:
                await asyncio.to_thread(_alembic_upgrade, self.url)
                logger.info("alembic upgrade head completed")
            except Exception:
                logger.exception(
                    "alembic upgrade failed; falling back to create_all"
                )
                await self.create_all()
                return
        await self.create_all()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def dispose(self) -> None:
        await self.engine.dispose()
