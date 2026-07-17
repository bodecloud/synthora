"""Synthora adapters: LLM providers, search engines, strategies, embeddings, MCP."""

from synthora.adapters.document_index import DocumentIndex, document_index
from synthora.adapters.embeddings import (
    EmbeddingRegistry,
    HashEmbeddings,
    OllamaEmbeddings,
    OpenAIEmbeddings,
    embedding_registry,
    resolve_default_embeddings,
)
from synthora.adapters.llm import LLMProviderRegistry, llm_registry
from synthora.adapters.mcp_client import MCPTool, load_mcp_tools
from synthora.adapters.page_fetch import fetch_page_text, is_fetchable_url
from synthora.adapters.search_engines import (
    SearchEngineRegistry,
    engine_is_usable,
    search_engine_registry,
)
from synthora.adapters.strategies import SearchStrategyRegistry, strategy_registry
from synthora.adapters.summarize import summarize_page

__all__ = [
    "DocumentIndex",
    "EmbeddingRegistry",
    "HashEmbeddings",
    "resolve_default_embeddings",
    "LLMProviderRegistry",
    "MCPTool",
    "OllamaEmbeddings",
    "OpenAIEmbeddings",
    "SearchEngineRegistry",
    "SearchStrategyRegistry",
    "document_index",
    "embedding_registry",
    "llm_registry",
    "load_mcp_tools",
    "engine_is_usable",
    "search_engine_registry",
    "strategy_registry",
    "fetch_page_text",
    "is_fetchable_url",
    "summarize_page",
]
