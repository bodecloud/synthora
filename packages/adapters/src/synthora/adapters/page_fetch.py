"""Fetch and extract readable text from public HTTP(S) page URLs.

Used by the researcher loop when search engines only return snippets.
Includes basic SSRF guards (private/link-local hosts, non-http schemes).
"""

from __future__ import annotations

import ipaddress
import logging
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("synthora.adapters.page_fetch")

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = data.strip()
        if text:
            self._chunks.append(text)

    def text(self) -> str:
        return _WS_RE.sub(" ", " ".join(self._chunks)).strip()


def _host_is_blocked(hostname: str) -> bool:
    host = (hostname or "").strip().lower().rstrip(".")
    if not host or host == "localhost" or host.endswith(".localhost"):
        return True
    if host in {"metadata.google.internal", "metadata"}:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    )


def is_fetchable_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.hostname:
        return False
    return not _host_is_blocked(parsed.hostname)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        return _WS_RE.sub(" ", _TAG_RE.sub(" ", html or "")).strip()
    return parser.text()


async def fetch_page_text(
    url: str,
    *,
    timeout: float = 15.0,
    max_bytes: int = 500_000,
) -> str:
    """Return extracted page text, or empty string on skip/failure."""
    if not is_fetchable_url(url):
        return ""
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "SynthoraResearchBot/1.0"},
        ) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                ctype = (resp.headers.get("content-type") or "").lower()
                if ctype and not any(
                    t in ctype for t in ("text/", "json", "xml", "html")
                ):
                    return ""
                encoding = resp.encoding or "utf-8"
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                    total += len(chunk)
                    if total >= max_bytes:
                        break
                raw = b"".join(chunks)[:max_bytes]
        text = raw.decode(encoding, errors="replace")
        if "html" in ctype or "<html" in text[:500].lower():
            return html_to_text(text)
        return _WS_RE.sub(" ", text).strip()
    except Exception:
        logger.debug("page fetch failed for %s", url, exc_info=True)
        return ""
