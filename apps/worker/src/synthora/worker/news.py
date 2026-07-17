"""News subscription fetch helpers (LDR-inspired)."""

from __future__ import annotations

import logging
from typing import Optional

from synthora.adapters import search_engine_registry
from synthora.core.models import NewsItem, NewsSubscription, utcnow
from synthora.persistence import NewsRepository

logger = logging.getLogger("synthora.worker.news")

# Prefer Fake-safe / offline engines first; network engines are best-effort.
DEFAULT_NEWS_ENGINES = ("searxng", "duckduckgo", "ddg")


def _resolve_news_engines(engine_names: Optional[list[str]] = None):
    names = list(engine_names or DEFAULT_NEWS_ENGINES)
    engines = []
    for name in names:
        try:
            engines.append(search_engine_registry.resolve(name))
        except KeyError:
            logger.debug("news engine %s not registered, skipping", name)
        except Exception:
            logger.debug(
                "news engine %s failed to construct, skipping", name, exc_info=True
            )
    return engines


async def fetch_subscription_news(
    repo: NewsRepository,
    sub: NewsSubscription,
    *,
    engine_names: Optional[list[str]] = None,
    max_results: int = 8,
) -> list[NewsItem]:
    """Pull search results for a subscription and persist them as news_items.

    Does not advance ``last_run_at`` when no engines resolve or every engine
    fails — so the poller will retry instead of treating total failure as success.
    """
    engines = _resolve_news_engines(engine_names)
    if not engines:
        logger.error(
            "no usable news engines for subscription %s; not advancing last_run_at",
            sub.id,
        )
        return []

    seen_urls: set[str] = set()
    collected: list[NewsItem] = []
    failures = 0
    for engine in engines:
        try:
            results = await engine.search(sub.query, max_results=max_results)
        except Exception:
            failures += 1
            logger.exception(
                "news fetch failed for subscription %s via %s",
                sub.id,
                getattr(engine, "name", "?"),
            )
            continue
        for result in results:
            url = (result.url or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            collected.append(
                NewsItem(
                    subscription_id=sub.id,
                    title=result.title or url,
                    url=url,
                    summary=result.snippet or result.content or "",
                )
            )
            if len(collected) >= max_results:
                break
        if len(collected) >= max_results:
            break

    if not collected and failures == len(engines):
        logger.error(
            "all news engines failed for subscription %s; not advancing last_run_at",
            sub.id,
        )
        return []

    if collected:
        await repo.add_items(collected)
    sub.last_run_at = utcnow()
    await repo.update_subscription(sub)
    return collected


async def poll_due_subscriptions(repo: NewsRepository) -> int:
    """Fetch all due subscriptions. Returns number of subscriptions polled."""
    due = await repo.list_due_subscriptions()
    for sub in due:
        await fetch_subscription_news(repo, sub)
    return len(due)
