"""U2: adapter registries, strategies with fakes."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from synthora.adapters import (
    embedding_registry,
    llm_registry,
    search_engine_registry,
    strategy_registry,
    summarize_page,
)
from synthora.adapters.embeddings import HashEmbeddings, OpenAIEmbeddings
from synthora.adapters.llm import OpenAICompatibleModel, strip_think_tags
from synthora.adapters.search_engines import CollectionEngine
from synthora.adapters.strategies import (
    FocusedIterationStandardStrategy,
    FocusedIterationStrategy,
    LangGraphAgentStrategy,
    SourceBasedStrategy,
    TopicOrganizationStrategy,
    dedupe_results,
)
from synthora.core.models import SearchResult

from tests.conftest import FakeChatModel, FakeSearchEngine

# ---------------------------------------------------------------------------
# LLM providers
# ---------------------------------------------------------------------------


EXPECTED_LLM_PROVIDERS = {
    "openai",
    "openai-compatible",
    "ollama",
    "anthropic",
    "google",
    "openrouter",
    "lmstudio",
    "deepseek",
    "xai",
    "together",
    "custom_openai_endpoint",
}


def test_llm_registry_resolution():
    model = llm_registry.resolve("openai:gpt-4o-mini")
    assert isinstance(model, OpenAICompatibleModel)
    assert model.model == "gpt-4o-mini"
    # bare model string defaults to openai
    assert llm_registry.resolve("gpt-4o").model == "gpt-4o"
    with pytest.raises(KeyError):
        llm_registry.resolve("nonexistent:model")


def test_llm_registry_lists_full_parity_providers():
    assert EXPECTED_LLM_PROVIDERS <= set(llm_registry.providers())


@pytest.mark.parametrize(
    "provider,env_key,default_base",
    [
        ("openrouter", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1"),
        ("deepseek", "DEEPSEEK_API_KEY", "https://api.deepseek.com"),
        ("xai", "XAI_API_KEY", "https://api.x.ai/v1"),
        ("together", "TOGETHER_API_KEY", "https://api.together.xyz/v1"),
        ("lmstudio", "LMSTUDIO_API_KEY", "http://localhost:1234/v1"),
    ],
)
def test_llm_provider_aliases_are_openai_compatible(
    provider, env_key, default_base, monkeypatch
):
    monkeypatch.setenv(env_key, "test-key")
    model = llm_registry.resolve(f"{provider}:test-model")
    assert isinstance(model, OpenAICompatibleModel)
    assert model.model == "test-model"
    assert model.base_url.rstrip("/") == default_base.rstrip("/")
    assert model.api_key == "test-key"


def test_anthropic_uses_native_messages_client(monkeypatch):
    from synthora.adapters.llm import AnthropicModel

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    model = llm_registry.resolve("anthropic:claude-test")
    assert isinstance(model, AnthropicModel)
    assert model.model == "claude-test"
    assert model.base_url.rstrip("/") == "https://api.anthropic.com"
    assert model.api_key == "test-key"


def test_google_and_custom_openai_endpoint(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "gkey")
    google = llm_registry.resolve("google:gemini-2.0-flash")
    assert isinstance(google, OpenAICompatibleModel)
    assert "googleapis.com" in google.base_url
    assert google.api_key == "gkey"

    monkeypatch.setenv("CUSTOM_OPENAI_BASE_URL", "http://vllm:8000/v1")
    monkeypatch.setenv("CUSTOM_OPENAI_API_KEY", "ckey")
    custom = llm_registry.resolve("custom_openai_endpoint:my-model")
    assert isinstance(custom, OpenAICompatibleModel)
    assert custom.base_url == "http://vllm:8000/v1"
    assert custom.api_key == "ckey"


def test_strip_think_tags():
    assert strip_think_tags("<think>internal</think>answer") == "answer"
    assert strip_think_tags("plain") == "plain"


# ---------------------------------------------------------------------------
# Search engines
# ---------------------------------------------------------------------------


EXPECTED_ENGINES = {
    "searxng",
    "tavily",
    "arxiv",
    "semantic_scholar",
    "none",
    "null",
    "duckduckgo",
    "ddg",
    "brave",
    "wikipedia",
    "pubmed",
    "github",
    "elasticsearch",
    "serper",
    "google_pse",
    "openalex",
    "wayback",
    "stackexchange",
    "exa",
    "bing",
    "guardian",
    "collection",
}


def test_search_engine_registry():
    assert EXPECTED_ENGINES <= set(search_engine_registry.engines())
    with pytest.raises(KeyError):
        search_engine_registry.resolve("missing")


async def test_null_engine():
    engine = search_engine_registry.resolve("none")
    assert await engine.search("anything") == []
    null = search_engine_registry.resolve("null")
    assert null.name == "null"
    assert await null.search("x") == []


async def test_collection_engine_offline():
    docs = [
        {
            "url": "https://local/a",
            "title": "Quantum Computing",
            "content": "error correction codes for qubits",
        },
        {
            "url": "https://local/b",
            "title": "Cooking",
            "content": "pasta recipes",
        },
    ]
    engine = CollectionEngine(documents=docs)
    hits = await engine.search("qubit", max_results=5)
    assert len(hits) == 1
    assert hits[0].url == "https://local/a"

    registered = search_engine_registry.resolve("collection")
    assert registered.name == "collection"
    assert await registered.search("no-match-zzz") == []


async def test_serper_returns_empty_without_key(monkeypatch):
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    engine = search_engine_registry.resolve("serper")
    assert await engine.search("q") == []


async def test_brave_returns_empty_without_key(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    engine = search_engine_registry.resolve("brave")
    assert await engine.search("q") == []


def _mock_async_client(json_payload: dict):
    """Return a patch context for httpx.AsyncClient that yields json_payload."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=json_payload)
    resp.text = json.dumps(json_payload)
    client = AsyncMock()
    client.get = AsyncMock(return_value=resp)
    client.post = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return patch(
        "synthora.adapters.search_engines.httpx.AsyncClient", return_value=client
    )


async def test_wikipedia_engine_mocked():
    payload = {
        "query": {
            "search": [
                {
                    "pageid": 1,
                    "title": "Python (programming language)",
                    "snippet": "A <span>language</span>",
                }
            ]
        }
    }
    with _mock_async_client(payload):
        engine = search_engine_registry.resolve("wikipedia")
        results = await engine.search("python", max_results=2)
    assert results
    assert "Python" in results[0].title
    assert "<span>" not in results[0].snippet


async def test_duckduckgo_engine_mocked():
    payload = {
        "Heading": "Test",
        "AbstractText": "An abstract about testing.",
        "AbstractURL": "https://example.com/test",
        "RelatedTopics": [
            {
                "Text": "Related - more info",
                "FirstURL": "https://example.com/related",
            }
        ],
    }
    with _mock_async_client(payload):
        engine = search_engine_registry.resolve("duckduckgo")
        results = await engine.search("testing", max_results=5)
    assert len(results) >= 1
    assert results[0].engine == "duckduckgo"
    assert search_engine_registry.resolve("ddg").name == "duckduckgo"


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


async def test_hash_embeddings_deterministic():
    emb = HashEmbeddings(dims=32)
    a = await emb.embed(["hello world"])
    b = await emb.embed(["hello world"])
    c = await emb.embed(["different"])
    assert a == b
    assert a != c
    assert len(a[0]) == 32
    norm = sum(x * x for x in a[0]) ** 0.5
    assert abs(norm - 1.0) < 1e-6


def test_embedding_registry():
    assert {"openai", "ollama", "hash"} <= set(embedding_registry.providers())
    model = embedding_registry.resolve("hash:test")
    assert isinstance(model, HashEmbeddings)
    assert isinstance(
        embedding_registry.resolve("openai:text-embedding-3-small"), OpenAIEmbeddings
    )
    with pytest.raises(KeyError):
        embedding_registry.resolve("missing:model")


# ---------------------------------------------------------------------------
# Summarize
# ---------------------------------------------------------------------------


async def test_summarize_page_short_passthrough():
    llm = FakeChatModel(responses=["should not be called"])
    out = await summarize_page(llm, "T", "short content", max_chars=100)
    assert out == "short content"
    assert llm.calls == []


async def test_summarize_page_long_uses_llm():
    llm = FakeChatModel(responses=["compressed summary"])
    long = "x" * 5000
    out = await summarize_page(llm, "Big Page", long, max_chars=100)
    assert out == "compressed summary"
    assert len(llm.calls) == 1


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def test_dedupe_prefers_higher_score():
    results = [
        SearchResult(url="https://x.com/a", score=0.2, title="low"),
        SearchResult(url="https://x.com/a/", score=0.9, title="high"),
        SearchResult(url="https://x.com/b", score=0.5, title="other"),
    ]
    unique = dedupe_results(results)
    assert len(unique) == 2
    assert unique[0].title == "high"


async def test_source_based_strategy_decomposes_and_merges():
    llm = FakeChatModel(responses=["query one\nquery two\nquery three"])
    engine = FakeSearchEngine()
    strategy = SourceBasedStrategy()
    results = await strategy.run("quantum error correction", engines=[engine], llm=llm)
    assert engine.queries == ["query one", "query two", "query three"]
    assert results and all(r.url.startswith("https://example.com") for r in results)


async def test_focused_iteration_refines_query():
    llm = FakeChatModel(responses=["refined query", "another refinement"])
    engine = FakeSearchEngine()
    strategy = FocusedIterationStrategy(iterations=2)
    await strategy.run("topic", engines=[engine], llm=llm)
    assert engine.queries[0] == "topic"
    assert engine.queries[1] == "refined query"


async def test_focused_iteration_standard_elongates_snippets():
    llm = FakeChatModel(responses=["refined"])
    long_content = "citation-worthy detail " * 40
    engine = FakeSearchEngine(
        results=[
            SearchResult(
                url="https://example.com/c",
                title="Cite me",
                snippet="short",
                content=long_content,
                engine="fake",
                score=1.0,
            )
        ]
    )
    strategy = FocusedIterationStandardStrategy(iterations=1)
    results = await strategy.run("topic", engines=[engine], llm=llm)
    assert results
    assert len(results[0].snippet) > len("short")
    assert results[0].snippet.startswith("citation-worthy")


async def test_topic_organization_clusters():
    cluster_json = json.dumps(
        {"topic": "Physics", "lead": "About qubits", "indices": [0]}
    )
    llm = FakeChatModel(
        responses=[
            "sub q1\nsub q2\nsub q3",  # SourceBased decompose
            cluster_json,  # clustering
        ]
    )
    engine = FakeSearchEngine()
    strategy = TopicOrganizationStrategy()
    results = await strategy.run("quantum", engines=[engine], llm=llm)
    assert results
    assert any(r.metadata.get("topic") == "Physics" for r in results)


async def test_langgraph_agent_picks_engines():
    llm = FakeChatModel(
        responses=[
            json.dumps({"query": "q1", "engine": "fake"}),
            json.dumps({"query": "q2", "engine": "fake"}),
        ]
    )
    engine = FakeSearchEngine()
    strategy = LangGraphAgentStrategy(iterations=2)
    results = await strategy.run("topic", engines=[engine], llm=llm)
    assert results
    assert "q1" in engine.queries
    assert "q2" in engine.queries


async def test_strategy_survives_engine_failure():
    class BrokenEngine:
        name = "broken"

        async def search(self, query, *, max_results=5):
            raise RuntimeError("boom")

    llm = FakeChatModel(responses=["q1\nq2"])
    good = FakeSearchEngine()
    strategy = SourceBasedStrategy()
    results = await strategy.run("t", engines=[BrokenEngine(), good], llm=llm)
    assert results  # good engine results still returned


EXPECTED_STRATEGIES = {
    "source_based",
    "source-based",
    "focused_iteration",
    "focused-iteration",
    "focused_iteration_standard",
    "topic_organization",
    "topic",
    "langgraph_agent",
    "langgraph-agent",
}


def test_strategy_registry():
    assert EXPECTED_STRATEGIES <= set(strategy_registry.strategies())
    assert strategy_registry.resolve("source_based").name == "source_based"
    assert strategy_registry.resolve("source-based").name == "source_based"
    assert (
        strategy_registry.resolve("focused_iteration_standard").name
        == "focused_iteration_standard"
    )
    assert strategy_registry.resolve("topic").name == "topic_organization"
    assert strategy_registry.resolve("langgraph-agent").name == "langgraph_agent"
