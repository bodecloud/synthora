"""Ports (protocols) that adapters and platform services implement.

These keep orchestration/intelligence decoupled from concrete providers
(R-LDR-4) and from the persistence/queue implementations (R-LDR-1/2).
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional, Protocol, runtime_checkable

from synthora.core.events import ProgressEvent
from synthora.core.models import ResearchRun, SearchResult


@runtime_checkable
class ChatModel(Protocol):
    """Minimal async chat interface every LLM provider adapter satisfies."""

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
    ) -> str: ...


@runtime_checkable
class SearchEngine(Protocol):
    """A single retrieval backend (SearXNG, Tavily, arXiv, ...)."""

    name: str

    async def search(
        self, query: str, *, max_results: int = 5
    ) -> list[SearchResult]: ...


@runtime_checkable
class EmbeddingModel(Protocol):
    """Dense embedding provider used for similarity / knowledge-map insert."""

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@runtime_checkable
class SearchStrategy(Protocol):
    """How multiple queries/engines are combined for one research topic."""

    name: str

    async def run(
        self,
        topic: str,
        *,
        engines: list[SearchEngine],
        llm: ChatModel,
        max_results: int = 8,
    ) -> list[SearchResult]: ...


EventSink = Callable[[ProgressEvent], Awaitable[None]]


class RunRepository(Protocol):
    async def create(self, run: ResearchRun) -> ResearchRun: ...

    async def get(self, run_id: str) -> Optional[ResearchRun]: ...

    async def update(self, run: ResearchRun) -> ResearchRun: ...

    async def list_runs(
        self, *, workspace_id: Optional[str] = None, limit: int = 50
    ) -> list[ResearchRun]: ...


class JobQueue(Protocol):
    async def enqueue(self, run_id: str, payload: dict[str, Any]) -> None: ...

    async def dequeue(self, *, timeout: float = 5.0) -> Optional[dict[str, Any]]: ...
