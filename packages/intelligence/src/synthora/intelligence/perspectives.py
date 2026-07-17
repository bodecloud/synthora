"""Perspective discovery (R-STORM-1).

STORM mines perspectives from related articles; we mine them directly from
the research brief plus optional retrieved context, producing N expert
personas with distinct focus areas. When a Wikipedia engine is available,
TOC section headings seed persona discovery (Wikipedia-TOC mining).
"""

from __future__ import annotations

import re
from urllib.parse import quote

import httpx
from synthora.core.models import Perspective
from synthora.core.parsing import parse_json_response
from synthora.core.ports import ChatModel


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


class PerspectiveEngine:
    def __init__(self, llm: ChatModel) -> None:
        self.llm = llm

    async def discover(
        self, brief: str, *, count: int = 3, context: str = ""
    ) -> list[Perspective]:
        raw = await self.llm.complete(
            [
                {
                    "role": "system",
                    "content": (
                        f"Identify {count} distinct expert perspectives for "
                        "researching the topic. Each expert must examine the topic "
                        "from a genuinely different angle (e.g. practitioner, "
                        "skeptic, historian, economist, engineer).\n"
                        'Reply JSON: [{"name": "...", "description": "...", '
                        '"focus": "..."}]'
                    ),
                },
                {
                    "role": "user",
                    "content": brief + (f"\n\nBackground:\n{context}" if context else ""),
                },
            ]
        )
        return self._parse_perspectives(raw, brief=brief, count=count)

    async def mine_from_wikipedia_toc(
        self,
        topic: str,
        *,
        count: int = 3,
        lang: str = "en",
        timeout: float = 20.0,
    ) -> list[Perspective]:
        """Derive expert personas from a Wikipedia article's table of contents.

        Fetches TOC section headings via the MediaWiki Action API (search +
        parse sections / tocdata), then asks the LLM to turn those angles into
        distinct research personas. Falls back to ``discover`` if the fetch
        yields no usable sections.
        """
        sections = await self._fetch_wikipedia_toc(
            topic, lang=lang, timeout=timeout
        )
        if not sections:
            return await self.discover(topic, count=count)

        toc_block = "\n".join(f"- {s}" for s in sections[:40])
        raw = await self.llm.complete(
            [
                {
                    "role": "system",
                    "content": (
                        f"Using the Wikipedia table-of-contents sections below, "
                        f"identify {count} distinct expert perspectives for "
                        "researching the topic. Each persona should map to one or "
                        "more TOC themes and examine a genuinely different angle.\n"
                        'Reply JSON: [{"name": "...", "description": "...", '
                        '"focus": "..."}]'
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Topic: {topic}\n\nWikipedia TOC sections:\n{toc_block}"
                    ),
                },
            ]
        )
        return self._parse_perspectives(raw, brief=topic, count=count)

    async def _fetch_wikipedia_toc(
        self,
        topic: str,
        *,
        lang: str = "en",
        timeout: float = 20.0,
    ) -> list[str]:
        """Return section heading strings for the best-matching Wikipedia page."""
        base = f"https://{lang}.wikipedia.org/w/api.php"
        headers = {
            "User-Agent": "SynthoraResearchBot/0.1 (https://github.com/bolabaden/synthora)"
        }
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
                search = await client.get(
                    base,
                    params={
                        "action": "query",
                        "list": "search",
                        "srsearch": topic,
                        "srlimit": 1,
                        "format": "json",
                        "utf8": 1,
                    },
                )
                search.raise_for_status()
                hits = (search.json().get("query") or {}).get("search") or []
                if not hits:
                    # try the topic as a direct page title
                    title = topic
                else:
                    title = hits[0].get("title") or topic

                parsed = await client.get(
                    base,
                    params={
                        "action": "parse",
                        "page": title,
                        "prop": "sections",
                        "format": "json",
                        "redirects": 1,
                    },
                )
                if parsed.status_code == 404:
                    return []
                parsed.raise_for_status()
                data = parsed.json()
                if "error" in data:
                    # REST fallback: mobile-sections TOC
                    return await self._fetch_wikipedia_toc_rest(
                        title, lang=lang, client=client
                    )
                sections = (data.get("parse") or {}).get("sections") or []
                lines = [
                    _strip_html(s.get("line") or s.get("anchor") or "")
                    for s in sections
                    if isinstance(s, dict)
                ]
                return [line for line in lines if line]
        except Exception:
            return []

    async def _fetch_wikipedia_toc_rest(
        self,
        title: str,
        *,
        lang: str,
        client: httpx.AsyncClient,
    ) -> list[str]:
        slug = quote(title.replace(" ", "_"), safe="")
        url = (
            f"https://{lang}.wikipedia.org/api/rest_v1/page/mobile-sections/{slug}"
        )
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []
        lines: list[str] = []
        for block in data.get("remaining") or []:
            if not isinstance(block, dict):
                continue
            line = _strip_html(block.get("line") or block.get("id") or "")
            if line:
                lines.append(line)
        return lines

    async def generate_questions(
        self, perspective: Perspective, brief: str, *, count: int = 3
    ) -> list[str]:
        """Perspective-guided question asking (the core STORM move)."""
        raw = await self.llm.complete(
            [
                {
                    "role": "system",
                    "content": (
                        f"You are {perspective.name}: {perspective.description}. "
                        f"Your focus: {perspective.focus}.\n"
                        f"Ask {count} incisive research questions about the topic "
                        "that only someone with your perspective would think to ask. "
                        "Return one question per line."
                    ),
                },
                {"role": "user", "content": brief},
            ]
        )
        questions = [q.strip("-• ").strip() for q in raw.splitlines() if q.strip()]
        return questions[:count] or [brief]

    def _parse_perspectives(
        self, raw: str, *, brief: str, count: int
    ) -> list[Perspective]:
        parsed = parse_json_response(raw)
        perspectives: list[Perspective] = []
        if isinstance(parsed, list):
            for item in parsed[:count]:
                if isinstance(item, dict) and item.get("name"):
                    perspectives.append(
                        Perspective(
                            name=str(item["name"]),
                            description=str(item.get("description", "")),
                            focus=str(item.get("focus", "")),
                        )
                    )
        if not perspectives:  # deterministic fallback keeps pipelines alive
            perspectives = [
                Perspective(
                    name=f"Expert {i + 1}",
                    description="General domain expert",
                    focus=brief[:100],
                )
                for i in range(count)
            ]
        return perspectives
