"""Shared fixtures: in-memory database and fake adapters."""

from __future__ import annotations

import pytest
from synthora.core.models import SearchResult
from synthora.orchestration.checkpoint import reset_checkpointer
from synthora.persistence.database import Database


@pytest.fixture(autouse=True)
def _fresh_checkpointer():
    """Isolate LangGraph MemorySaver state between tests."""
    reset_checkpointer()
    yield
    reset_checkpointer()


@pytest.fixture
async def db() -> Database:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_all()
    yield database
    await database.dispose()


class FakeChatModel:
    """Scripted chat model: returns queued responses, else a default."""

    def __init__(self, responses: list[str] | None = None, default: str = "ok") -> None:
        self.responses = list(responses or [])
        self.default = default
        self.calls: list[list[dict[str, str]]] = []

    async def complete(self, messages, *, temperature=0.3, max_tokens=None) -> str:
        self.calls.append(messages)
        if self.responses:
            return self.responses.pop(0)
        return self.default


class FakeSearchEngine:
    name = "fake"

    def __init__(self, results: list[SearchResult] | None = None) -> None:
        self._results = results or [
            SearchResult(
                url="https://example.com/a",
                title="Example A",
                snippet="alpha snippet",
                content="alpha content",
                engine="fake",
                score=0.9,
            ),
            SearchResult(
                url="https://example.com/b",
                title="Example B",
                snippet="beta snippet",
                content="beta content",
                engine="fake",
                score=0.7,
            ),
        ]
        self.queries: list[str] = []

    async def search(self, query: str, *, max_results: int = 5):
        self.queries.append(query)
        return self._results[:max_results]


@pytest.fixture
def fake_llm() -> FakeChatModel:
    return FakeChatModel()


@pytest.fixture
def fake_engine() -> FakeSearchEngine:
    return FakeSearchEngine()
