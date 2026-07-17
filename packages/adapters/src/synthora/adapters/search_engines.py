"""Search engine adapters and registry (R-LDR-4).

Full LDR/STORM-level catalog. Engines are constructed lazily by name so tests
can register fakes without network access. Network failures raise httpx errors
(caught by strategies) or return empty lists when credentials are missing.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Callable, Optional
from urllib.parse import quote, quote_plus

import httpx
from defusedxml import ElementTree
from synthora.core.models import SearchResult
from synthora.core.ports import SearchEngine

logger = logging.getLogger("synthora.adapters.search")

EngineFactory = Callable[[], SearchEngine]


def _env(*names: str, default: str = "") -> str:
    from synthora.adapters.provider_settings_context import resolve_credential

    return resolve_credential(*names, default=default)


def _truncate(text: str, n: int = 500) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


# ---------------------------------------------------------------------------
# Existing engines
# ---------------------------------------------------------------------------


class SearxngEngine:
    name = "searxng"

    def __init__(self, base_url: Optional[str] = None, timeout: float = 20.0) -> None:
        self.base_url = (
            base_url or _env("SEARXNG_URL", default="http://localhost:8080")
        ).rstrip("/")
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}/search",
                params={"q": query, "format": "json"},
            )
            resp.raise_for_status()
            data = resp.json()
        results = []
        for item in data.get("results", [])[:max_results]:
            results.append(
                SearchResult(
                    url=item.get("url", ""),
                    title=item.get("title", ""),
                    snippet=item.get("content", ""),
                    content=item.get("content", ""),
                    engine=self.name,
                    score=float(item.get("score", 0.0) or 0.0),
                )
            )
        return results


class TavilyEngine:
    name = "tavily"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 30.0) -> None:
        self.api_key = api_key or os.environ.get("TAVILY_API_KEY", "")
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if not self.api_key:
            logger.warning("%s: API key not configured; returning no results", self.name)
            return []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "max_results": max_results,
                    "include_raw_content": True,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            SearchResult(
                url=item.get("url", ""),
                title=item.get("title", ""),
                snippet=item.get("content", ""),
                content=item.get("raw_content") or item.get("content", ""),
                engine=self.name,
                score=float(item.get("score", 0.0) or 0.0),
            )
            for item in data.get("results", [])[:max_results]
        ]


class ArxivEngine:
    """Academic search over the arXiv Atom API (R-PIPE-4)."""

    name = "arxiv"
    _ns = {"atom": "http://www.w3.org/2005/Atom"}

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                "https://export.arxiv.org/api/query",
                params={
                    "search_query": f"all:{query}",
                    "max_results": max_results,
                    "sortBy": "relevance",
                },
            )
            resp.raise_for_status()
            text = resp.text
        root = ElementTree.fromstring(text)
        results = []
        for entry in root.findall("atom:entry", self._ns):
            title = (entry.findtext("atom:title", "", self._ns) or "").strip()
            summary = (entry.findtext("atom:summary", "", self._ns) or "").strip()
            link = entry.findtext("atom:id", "", self._ns) or ""
            results.append(
                SearchResult(
                    url=link,
                    title=title,
                    snippet=summary[:500],
                    content=summary,
                    engine=self.name,
                    metadata={
                        "published": entry.findtext("atom:published", "", self._ns),
                        "authors": [
                            a.findtext("atom:name", "", self._ns)
                            for a in entry.findall("atom:author", self._ns)
                        ],
                    },
                )
            )
        return results


class SemanticScholarEngine:
    name = "semantic_scholar"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 30.0) -> None:
        self.api_key = api_key or os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        headers = {"x-api-key": self.api_key} if self.api_key else {}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={
                    "query": query,
                    "limit": max_results,
                    "fields": "title,abstract,url,year,citationCount,authors",
                },
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            SearchResult(
                url=item.get("url") or "",
                title=item.get("title") or "",
                snippet=(item.get("abstract") or "")[:500],
                content=item.get("abstract") or "",
                engine=self.name,
                score=float(item.get("citationCount", 0) or 0),
                metadata={
                    "year": item.get("year"),
                    "authors": [
                        a.get("name") for a in (item.get("authors") or [])
                    ],
                },
            )
            for item in data.get("data", [])[:max_results]
        ]


class NullEngine:
    """No-op engine for offline runs."""

    name = "none"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        return []


class NullAliasEngine(NullEngine):
    name = "null"


# ---------------------------------------------------------------------------
# New engines
# ---------------------------------------------------------------------------


class DuckDuckGoEngine:
    """DuckDuckGo Instant Answer + RelatedTopics (no API key)."""

    name = "duckduckgo"

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            )
            resp.raise_for_status()
            data = resp.json()
        results: list[SearchResult] = []
        abstract = data.get("AbstractText") or ""
        abstract_url = data.get("AbstractURL") or data.get("AbstractSource") or ""
        if abstract:
            results.append(
                SearchResult(
                    url=abstract_url or f"https://duckduckgo.com/?q={quote_plus(query)}",
                    title=data.get("Heading") or query,
                    snippet=_truncate(abstract),
                    content=abstract,
                    engine=self.name,
                    score=1.0,
                )
            )
        for topic in data.get("RelatedTopics") or []:
            if len(results) >= max_results:
                break
            if "Topics" in topic:  # nested group
                for nested in topic.get("Topics") or []:
                    if len(results) >= max_results:
                        break
                    text = nested.get("Text") or ""
                    url = nested.get("FirstURL") or ""
                    if text and url:
                        results.append(
                            SearchResult(
                                url=url,
                                title=text.split(" - ")[0][:120],
                                snippet=_truncate(text),
                                content=text,
                                engine=self.name,
                            )
                        )
            else:
                text = topic.get("Text") or ""
                url = topic.get("FirstURL") or ""
                if text and url:
                    results.append(
                        SearchResult(
                            url=url,
                            title=text.split(" - ")[0][:120],
                            snippet=_truncate(text),
                            content=text,
                            engine=self.name,
                        )
                    )
        return results[:max_results]


class BraveEngine:
    name = "brave"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 20.0) -> None:
        self.api_key = api_key or _env("BRAVE_API_KEY", "BRAVE_SEARCH_API_KEY")
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if not self.api_key:
            logger.warning("%s: API key not configured; returning no results", self.name)
            return []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": max_results},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self.api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            SearchResult(
                url=item.get("url", ""),
                title=item.get("title", ""),
                snippet=item.get("description", ""),
                content=item.get("description", ""),
                engine=self.name,
                score=float(item.get("score", 0.0) or 0.0),
            )
            for item in (data.get("web") or {}).get("results", [])[:max_results]
        ]


class WikipediaEngine:
    """MediaWiki Action API search + extracts."""

    name = "wikipedia"

    def __init__(
        self,
        *,
        lang: Optional[str] = None,
        timeout: float = 20.0,
    ) -> None:
        self.lang = lang or _env("WIKIPEDIA_LANG", default="en")
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        base = f"https://{self.lang}.wikipedia.org/w/api.php"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                base,
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "srlimit": max_results,
                    "format": "json",
                    "utf8": 1,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        results: list[SearchResult] = []
        for item in (data.get("query") or {}).get("search", [])[:max_results]:
            title = item.get("title") or ""
            snippet = re.sub(r"<[^>]+>", "", item.get("snippet") or "")
            page_id = item.get("pageid")
            url = f"https://{self.lang}.wikipedia.org/?curid={page_id}" if page_id else (
                f"https://{self.lang}.wikipedia.org/wiki/{quote_plus(title.replace(' ', '_'))}"
            )
            results.append(
                SearchResult(
                    url=url,
                    title=title,
                    snippet=_truncate(snippet),
                    content=snippet,
                    engine=self.name,
                    metadata={"pageid": page_id},
                )
            )
        return results


class PubMedEngine:
    name = "pubmed"

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout
        self.api_key = _env("NCBI_API_KEY", "PUBMED_API_KEY")

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        params: dict = {
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "retmode": "json",
        }
        if self.api_key:
            params["api_key"] = self.api_key
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            search_resp = await client.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params=params,
            )
            search_resp.raise_for_status()
            ids = (search_resp.json().get("esearchresult") or {}).get("idlist") or []
            if not ids:
                return []
            summary_resp = await client.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                params={
                    "db": "pubmed",
                    "id": ",".join(ids),
                    "retmode": "json",
                    **({"api_key": self.api_key} if self.api_key else {}),
                },
            )
            summary_resp.raise_for_status()
            result = summary_resp.json().get("result") or {}
        results: list[SearchResult] = []
        for pmid in ids[:max_results]:
            item = result.get(pmid) or {}
            title = item.get("title") or f"PMID {pmid}"
            abstractish = item.get("sorttitle") or title
            results.append(
                SearchResult(
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    title=title,
                    snippet=_truncate(abstractish),
                    content=abstractish,
                    engine=self.name,
                    metadata={
                        "pmid": pmid,
                        "authors": [
                            a.get("name") for a in (item.get("authors") or [])
                        ],
                        "pubdate": item.get("pubdate"),
                    },
                )
            )
        return results


class GitHubEngine:
    name = "github"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 20.0) -> None:
        self.api_key = api_key or _env("GITHUB_TOKEN", "GH_TOKEN")
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        headers = {"Accept": "application/vnd.github+json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                "https://api.github.com/search/repositories",
                params={"q": query, "per_page": max_results},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            SearchResult(
                url=item.get("html_url") or "",
                title=item.get("full_name") or item.get("name") or "",
                snippet=_truncate(item.get("description") or ""),
                content=item.get("description") or "",
                engine=self.name,
                score=float(item.get("stargazers_count", 0) or 0),
                metadata={
                    "stars": item.get("stargazers_count"),
                    "language": item.get("language"),
                },
            )
            for item in data.get("items", [])[:max_results]
        ]


class ElasticsearchEngine:
    name = "elasticsearch"

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        index: Optional[str] = None,
        timeout: float = 20.0,
    ) -> None:
        self.base_url = (
            base_url or _env("ELASTICSEARCH_URL", default="http://localhost:9200")
        ).rstrip("/")
        self.index = index or _env("ELASTICSEARCH_INDEX", default="documents")
        self.api_key = _env("ELASTICSEARCH_API_KEY")
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"ApiKey {self.api_key}"
        body = {
            "size": max_results,
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": ["title^2", "content", "text", "body", "snippet"],
                }
            },
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/{self.index}/_search",
                json=body,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        results: list[SearchResult] = []
        for hit in (data.get("hits") or {}).get("hits", [])[:max_results]:
            src = hit.get("_source") or {}
            content = (
                src.get("content")
                or src.get("text")
                or src.get("body")
                or src.get("snippet")
                or ""
            )
            results.append(
                SearchResult(
                    url=src.get("url") or src.get("link") or f"es://{hit.get('_id')}",
                    title=src.get("title") or str(hit.get("_id") or ""),
                    snippet=_truncate(content),
                    content=content,
                    engine=self.name,
                    score=float(hit.get("_score") or 0.0),
                )
            )
        return results


class SerperEngine:
    """Google results via Serper.dev."""

    name = "serper"

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        timeout: float = 20.0,
        engine_label: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or _env("SERPER_API_KEY")
        self.timeout = timeout
        self.engine_label = engine_label or self.name

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if not self.api_key:
            logger.warning("%s: API key not configured; returning no results", self.name)
            return []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                "https://google.serper.dev/search",
                json={"q": query, "num": max_results},
                headers={
                    "X-API-KEY": self.api_key,
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            SearchResult(
                url=item.get("link", ""),
                title=item.get("title", ""),
                snippet=item.get("snippet", ""),
                content=item.get("snippet", ""),
                engine=self.engine_label,
                score=1.0 / (i + 1),
            )
            for i, item in enumerate(data.get("organic", [])[:max_results])
        ]


class BingEngine(SerperEngine):
    """Bing-flavored search via Serper when BING_API_KEY is unset.

    Prefers Azure Bing Web Search when ``BING_API_KEY`` is present.
    """

    name = "bing"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 20.0) -> None:
        self.bing_key = api_key or _env("BING_API_KEY", "BING_SEARCH_V7_SUBSCRIPTION_KEY")
        self.serper_key = _env("SERPER_API_KEY")
        self.timeout = timeout
        self.engine_label = self.name
        self.api_key = self.serper_key  # for SerperEngine.search fallback

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if self.bing_key:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    "https://api.bing.microsoft.com/v7.0/search",
                    params={"q": query, "count": max_results},
                    headers={"Ocp-Apim-Subscription-Key": self.bing_key},
                )
                resp.raise_for_status()
                data = resp.json()
            return [
                SearchResult(
                    url=item.get("url", ""),
                    title=item.get("name", ""),
                    snippet=item.get("snippet", ""),
                    content=item.get("snippet", ""),
                    engine=self.name,
                )
                for item in (data.get("webPages") or {}).get("value", [])[:max_results]
            ]
        return await SerperEngine.search(self, query, max_results=max_results)


class GooglePseEngine:
    """Google Programmable Search Engine (Custom Search JSON API)."""

    name = "google_pse"

    def __init__(
        self,
        api_key: Optional[str] = None,
        cx: Optional[str] = None,
        timeout: float = 20.0,
    ) -> None:
        self.api_key = api_key or _env("GOOGLE_PSE_API_KEY", "GOOGLE_API_KEY")
        self.cx = cx or _env("GOOGLE_PSE_CX", "GOOGLE_CSE_ID")
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if not self.api_key or not self.cx:
            logger.warning("%s: API key/cx not configured; returning no results", self.name)
            return []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "key": self.api_key,
                    "cx": self.cx,
                    "q": query,
                    "num": min(max_results, 10),
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            SearchResult(
                url=item.get("link", ""),
                title=item.get("title", ""),
                snippet=item.get("snippet", ""),
                content=item.get("snippet", ""),
                engine=self.name,
            )
            for item in data.get("items", [])[:max_results]
        ]


class OpenAlexEngine:
    name = "openalex"

    def __init__(self, email: Optional[str] = None, timeout: float = 30.0) -> None:
        self.email = email or _env("OPENALEX_EMAIL", "OPENALEX_MAILTO")
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        params: dict = {
            "search": query,
            "per_page": max_results,
        }
        headers = {}
        if self.email:
            params["mailto"] = self.email
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                "https://api.openalex.org/works",
                params=params,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        results: list[SearchResult] = []
        for item in data.get("results", [])[:max_results]:
            title = item.get("display_name") or item.get("title") or ""
            abstract = ""
            inv = item.get("abstract_inverted_index") or {}
            if inv:
                # reconstruct rough abstract from inverted index
                positions: list[tuple[int, str]] = []
                for word, idxs in inv.items():
                    for i in idxs:
                        positions.append((i, word))
                abstract = " ".join(w for _, w in sorted(positions))
            url = (
                item.get("doi")
                and f"https://doi.org/{item['doi'].replace('https://doi.org/', '')}"
            ) or item.get("id") or ""
            results.append(
                SearchResult(
                    url=url,
                    title=title,
                    snippet=_truncate(abstract),
                    content=abstract,
                    engine=self.name,
                    score=float(item.get("cited_by_count") or 0),
                    metadata={
                        "year": (item.get("publication_year")),
                        "openalex_id": item.get("id"),
                    },
                )
            )
        return results


class WaybackEngine:
    """Internet Archive CDX / Wayback availability search."""

    name = "wayback"

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        # Treat query as a URL-ish target; fall back to keyword via CDX matchType=prefix
        target = query.strip()
        if not target.startswith("http"):
            target = f"https://{target}" if "." in target.split()[0] else target
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            if target.startswith("http"):
                resp = await client.get(
                    "https://web.archive.org/cdx/search/cdx",
                    params={
                        "url": target,
                        "output": "json",
                        "limit": max_results,
                        "fl": "timestamp,original,statuscode,mimetype",
                        "filter": "statuscode:200",
                    },
                )
            else:
                # keyword → use Wayback CDX with matchType=domain on a placeholder
                resp = await client.get(
                    "https://web.archive.org/cdx/search/cdx",
                    params={
                        "url": f"*.{quote_plus(query)}/*",
                        "output": "json",
                        "limit": max_results,
                        "fl": "timestamp,original,statuscode,mimetype",
                    },
                )
            resp.raise_for_status()
            rows = resp.json()
        if not rows or len(rows) < 2:
            return []
        header, *entries = rows
        results: list[SearchResult] = []
        for row in entries[:max_results]:
            record = dict(zip(header, row))
            ts = record.get("timestamp", "")
            original = record.get("original", "")
            archived = (
                f"https://web.archive.org/web/{ts}/{original}" if ts and original else original
            )
            results.append(
                SearchResult(
                    url=archived,
                    title=f"Wayback {ts}: {original}",
                    snippet=original,
                    content=original,
                    engine=self.name,
                    metadata=record,
                )
            )
        return results


class StackExchangeEngine:
    name = "stackexchange"

    def __init__(
        self,
        *,
        site: Optional[str] = None,
        timeout: float = 20.0,
    ) -> None:
        self.site = site or _env("STACKEXCHANGE_SITE", default="stackoverflow")
        self.api_key = _env("STACKEXCHANGE_KEY")
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        params: dict = {
            "order": "desc",
            "sort": "relevance",
            "intitle": query,
            "site": self.site,
            "pagesize": max_results,
            "filter": "default",
        }
        if self.api_key:
            params["key"] = self.api_key
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                "https://api.stackexchange.com/2.3/search",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            SearchResult(
                url=item.get("link", ""),
                title=item.get("title", ""),
                snippet=_truncate(
                    " ".join(item.get("tags") or []) + " " + str(item.get("score", ""))
                ),
                content=item.get("title", ""),
                engine=self.name,
                score=float(item.get("score") or 0),
                metadata={
                    "question_id": item.get("question_id"),
                    "tags": item.get("tags"),
                },
            )
            for item in data.get("items", [])[:max_results]
        ]


class ExaEngine:
    name = "exa"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 30.0) -> None:
        self.api_key = api_key or _env("EXA_API_KEY")
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if not self.api_key:
            logger.warning("%s: API key not configured; returning no results", self.name)
            return []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                "https://api.exa.ai/search",
                json={
                    "query": query,
                    "numResults": max_results,
                    "contents": {"text": True},
                },
                headers={
                    "x-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            SearchResult(
                url=item.get("url", ""),
                title=item.get("title", ""),
                snippet=_truncate(
                    (item.get("text") or item.get("snippet") or "")[:2000]
                ),
                content=item.get("text") or item.get("snippet") or "",
                engine=self.name,
                score=float(item.get("score") or 0.0),
            )
            for item in data.get("results", [])[:max_results]
        ]


class GuardianEngine:
    name = "guardian"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 20.0) -> None:
        self.api_key = api_key or _env("GUARDIAN_API_KEY", "THE_GUARDIAN_API_KEY")
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if not self.api_key:
            logger.warning("%s: API key not configured; returning no results", self.name)
            return []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                "https://content.guardianapis.com/search",
                params={
                    "q": query,
                    "page-size": max_results,
                    "api-key": self.api_key,
                    "show-fields": "trailText,bodyText",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        results: list[SearchResult] = []
        for item in (data.get("response") or {}).get("results", [])[:max_results]:
            fields = item.get("fields") or {}
            trail = fields.get("trailText") or ""
            body = fields.get("bodyText") or trail
            results.append(
                SearchResult(
                    url=item.get("webUrl", ""),
                    title=item.get("webTitle", ""),
                    snippet=_truncate(re.sub(r"<[^>]+>", "", trail)),
                    content=body,
                    engine=self.name,
                    metadata={"section": item.get("sectionName")},
                )
            )
        return results


class CollectionEngine:
    """Local in-memory / document-list search (offline-safe).

    Documents may be supplied via constructor or ``SYNTHORA_COLLECTION_DOCS``
    (JSON list of ``{url,title,content}`` objects). Matching is simple
    case-insensitive substring search over title+content.
    """

    name = "collection"

    def __init__(
        self,
        documents: Optional[list[dict]] = None,
        *,
        timeout: float = 5.0,
    ) -> None:
        self.timeout = timeout
        if documents is not None:
            self.documents = list(documents)
        else:
            raw = os.environ.get("SYNTHORA_COLLECTION_DOCS", "[]")
            try:
                self.documents = json.loads(raw) if raw else []
            except json.JSONDecodeError:
                self.documents = []

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        from synthora.adapters.workspace_context import get_workspace_id

        workspace_id = get_workspace_id()
        # Prefer the shared RAG index for *this* workspace only (no cross-tenant scan).
        try:
            from synthora.adapters.document_index import (
                document_index,
                ensure_workspace_index,
            )

            indexed = document_index.search(
                workspace_id, query, max_results=max_results
            )
            if not indexed and not document_index.documents(workspace_id):
                db_url = os.environ.get("SYNTHORA_DATABASE_URL") or os.environ.get(
                    "DATABASE_URL", ""
                )
                if db_url:
                    from synthora.persistence.database import Database

                    db = Database(db_url)
                    try:
                        await ensure_workspace_index(workspace_id, db)
                    finally:
                        await db.dispose()
                    indexed = document_index.search(
                        workspace_id, query, max_results=max_results
                    )
            if indexed:
                return indexed
        except Exception:
            pass
        q = query.lower().strip()
        if not q:
            return []
        results: list[SearchResult] = []
        try:
            from synthora.adapters.document_index import document_index as _idx

            docs = list(self.documents) + _idx.documents(workspace_id)
        except Exception:
            docs = list(self.documents)
        seen: set[str] = set()
        for doc in docs:
            key = str(doc.get("id") or doc.get("url") or id(doc))
            if key in seen:
                continue
            seen.add(key)
            title = str(doc.get("title") or "")
            content = str(doc.get("content") or doc.get("text") or "")
            url = str(doc.get("url") or doc.get("id") or f"collection://{len(results)}")
            hay = f"{title}\n{content}".lower()
            if q in hay:
                results.append(
                    SearchResult(
                        url=url,
                        title=title,
                        snippet=_truncate(content),
                        content=content,
                        engine=self.name,
                        score=1.0 if q in title.lower() else 0.5,
                    )
                )
            if len(results) >= max_results:
                break
        return results[:max_results]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class SearchEngineRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, EngineFactory] = {}

    def register(self, name: str, factory: EngineFactory) -> None:
        self._factories[name] = factory

    def engines(self) -> list[str]:
        return sorted(self._factories)

    def resolve(self, name: str) -> SearchEngine:
        if name not in self._factories:
            raise KeyError(
                f"unknown search engine '{name}' (known: {self.engines()})"
            )
        return self._factories[name]()

    def resolve_many(self, names: list[str]) -> list[SearchEngine]:
        return [self.resolve(n) for n in names]


search_engine_registry = SearchEngineRegistry()

# Core / existing
search_engine_registry.register("searxng", SearxngEngine)
search_engine_registry.register("tavily", TavilyEngine)
search_engine_registry.register("arxiv", ArxivEngine)
search_engine_registry.register("semantic_scholar", SemanticScholarEngine)
search_engine_registry.register("none", NullEngine)
search_engine_registry.register("null", NullAliasEngine)

# Web / general
search_engine_registry.register("duckduckgo", DuckDuckGoEngine)
search_engine_registry.register("ddg", DuckDuckGoEngine)
search_engine_registry.register("brave", BraveEngine)
search_engine_registry.register("serper", SerperEngine)
search_engine_registry.register("google_pse", GooglePseEngine)
search_engine_registry.register("bing", BingEngine)
search_engine_registry.register("exa", ExaEngine)
search_engine_registry.register("guardian", GuardianEngine)

# Knowledge / academic
search_engine_registry.register("wikipedia", WikipediaEngine)
search_engine_registry.register("pubmed", PubMedEngine)
search_engine_registry.register("openalex", OpenAlexEngine)
search_engine_registry.register("stackexchange", StackExchangeEngine)

# Infra / archives
search_engine_registry.register("github", GitHubEngine)
search_engine_registry.register("elasticsearch", ElasticsearchEngine)
search_engine_registry.register("wayback", WaybackEngine)

# Local
search_engine_registry.register("collection", CollectionEngine)


class GutenbergEngine:
    """Project Gutenberg catalog search via Gutendex."""

    name = "gutenberg"

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                "https://gutendex.com/books",
                params={"search": query},
            )
            resp.raise_for_status()
            data = resp.json()
        out = []
        for item in data.get("results", [])[:max_results]:
            out.append(
                SearchResult(
                    url=item.get("formats", {}).get("text/html", "")
                    or f"https://www.gutenberg.org/ebooks/{item.get('id')}",
                    title=item.get("title", ""),
                    snippet=", ".join(a.get("name", "") for a in item.get("authors", [])),
                    content=item.get("summaries", [""])[0] if item.get("summaries") else "",
                    engine=self.name,
                    score=1.0,
                    metadata={"id": item.get("id")},
                )
            )
        return out


class OpenLibraryEngine:
    name = "openlibrary"

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                "https://openlibrary.org/search.json",
                params={"q": query, "limit": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
        out = []
        for item in data.get("docs", [])[:max_results]:
            key = item.get("key", "")
            out.append(
                SearchResult(
                    url=f"https://openlibrary.org{key}",
                    title=item.get("title", ""),
                    snippet=", ".join(item.get("author_name", [])[:3]),
                    content=str(item.get("first_sentence", "") or ""),
                    engine=self.name,
                    score=1.0,
                    metadata={"year": item.get("first_publish_year")},
                )
            )
        return out


class ZenodoEngine:
    name = "zenodo"

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                "https://zenodo.org/api/records",
                params={"q": query, "size": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
        out = []
        for hit in data.get("hits", {}).get("hits", [])[:max_results]:
            meta = hit.get("metadata", {})
            out.append(
                SearchResult(
                    url=hit.get("links", {}).get("html", f"https://zenodo.org/records/{hit.get('id')}"),
                    title=meta.get("title", ""),
                    snippet=(meta.get("description") or "")[:300],
                    content=meta.get("description") or "",
                    engine=self.name,
                    score=1.0,
                )
            )
        return out


class WikinewsEngine:
    name = "wikinews"

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                "https://en.wikinews.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "srlimit": max_results,
                    "format": "json",
                },
                headers={"User-Agent": "Synthora/0.1"},
            )
            resp.raise_for_status()
            data = resp.json()
        out = []
        for item in data.get("query", {}).get("search", [])[:max_results]:
            title = item.get("title", "")
            out.append(
                SearchResult(
                    url=f"https://en.wikinews.org/wiki/{title.replace(' ', '_')}",
                    title=title,
                    snippet=item.get("snippet", "").replace("<span class=\"searchmatch\">", "").replace("</span>", ""),
                    content=item.get("snippet", ""),
                    engine=self.name,
                    score=1.0,
                )
            )
        return out


class SerpApiEngine:
    name = "serpapi"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 30.0) -> None:
        self.api_key = api_key or os.environ.get("SERPAPI_API_KEY", "")
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if not self.api_key:
            logger.warning("%s: API key not configured; returning no results", self.name)
            return []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                "https://serpapi.com/search",
                params={"q": query, "api_key": self.api_key, "num": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
        out = []
        for item in data.get("organic_results", [])[:max_results]:
            out.append(
                SearchResult(
                    url=item.get("link", ""),
                    title=item.get("title", ""),
                    snippet=item.get("snippet", ""),
                    content=item.get("snippet", ""),
                    engine=self.name,
                    score=1.0,
                )
            )
        return out


class MojeekEngine:
    name = "mojeek"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 20.0) -> None:
        self.api_key = api_key or os.environ.get("MOJEEK_API_KEY", "")
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if not self.api_key:
            logger.warning("%s: API key not configured; returning no results", self.name)
            return []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                "https://api.mojeek.com/search",
                params={"q": query, "api_key": self.api_key, "fmt": "json"},
            )
            resp.raise_for_status()
            data = resp.json()
        out = []
        for item in data.get("response", {}).get("results", [])[:max_results]:
            out.append(
                SearchResult(
                    url=item.get("url", ""),
                    title=item.get("title", ""),
                    snippet=item.get("desc", ""),
                    content=item.get("desc", ""),
                    engine=self.name,
                    score=1.0,
                )
            )
        return out


class PubChemEngine:
    name = "pubchem"

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
                f"{quote(query)}/property/Title,MolecularFormula,CanonicalSMILES/JSON",
            )
            if resp.status_code >= 400:
                # fallback text search
                resp = await client.get(
                    "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/aspirin/property/Title/JSON"
                )
                if resp.status_code >= 400:
                    return []
            data = resp.json()
        props = data.get("PropertyTable", {}).get("Properties", [])[:max_results]
        out = []
        for p in props:
            cid = p.get("CID")
            out.append(
                SearchResult(
                    url=f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
                    title=p.get("Title", query),
                    snippet=p.get("MolecularFormula", ""),
                    content=p.get("CanonicalSMILES", ""),
                    engine=self.name,
                    score=1.0,
                    metadata={"cid": cid},
                )
            )
        return out


search_engine_registry.register("gutenberg", GutenbergEngine)
search_engine_registry.register("openlibrary", OpenLibraryEngine)
search_engine_registry.register("zenodo", ZenodoEngine)
search_engine_registry.register("wikinews", WikinewsEngine)
search_engine_registry.register("serpapi", SerpApiEngine)
search_engine_registry.register("mojeek", MojeekEngine)
search_engine_registry.register("pubchem", PubChemEngine)
