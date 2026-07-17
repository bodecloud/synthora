"""Token-limit detection and truncation helpers (ODR parity)."""

from __future__ import annotations

import re
from typing import Optional

_TOKEN_LIMIT_PATTERNS = (
    re.compile(r"context.?length", re.I),
    re.compile(r"maximum.?context", re.I),
    re.compile(r"token.?limit", re.I),
    re.compile(r"too many tokens", re.I),
    re.compile(r"prompt is too long", re.I),
    re.compile(r"max_tokens", re.I),
    re.compile(r"context_length_exceeded", re.I),
)


def is_token_limit_error(exc: BaseException | str) -> bool:
    text = str(exc)
    return any(p.search(text) for p in _TOKEN_LIMIT_PATTERNS)


def truncate_middle(text: str, max_chars: int) -> str:
    """Keep head and tail when truncating long context (ODR-style)."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head - 20
    if tail < 0:
        return text[:max_chars]
    return f"{text[:head]}\n\n...[truncated]...\n\n{text[-tail:]}"


async def complete_with_retry(
    llm,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.3,
    max_tokens: Optional[int] = None,
    max_attempts: int = 3,
    truncate_user_to: Optional[int] = None,
) -> str:
    """Call ``llm.complete``, truncating the last user message on token errors."""
    msgs = [dict(m) for m in messages]
    last_err: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return await llm.complete(
                msgs, temperature=temperature, max_tokens=max_tokens
            )
        except Exception as exc:
            last_err = exc
            if not is_token_limit_error(exc) or attempt >= max_attempts - 1:
                raise
            limit = truncate_user_to or 12_000
            limit = max(2000, int(limit * (0.6**attempt)))
            for i in range(len(msgs) - 1, -1, -1):
                if msgs[i].get("role") == "user":
                    msgs[i]["content"] = truncate_middle(msgs[i]["content"], limit)
                    break
    raise last_err or RuntimeError("complete_with_retry failed")
