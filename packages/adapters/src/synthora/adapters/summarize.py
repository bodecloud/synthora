"""Page content summarization before stuffing into LLM context (R-ODR)."""

from __future__ import annotations

from synthora.core.ports import ChatModel


async def summarize_page(
    llm: ChatModel,
    title: str,
    content: str,
    max_chars: int = 2000,
) -> str:
    """Compress page content to roughly ``max_chars`` characters.

    Short pages are returned unchanged. Longer pages are truncated to a
    generous window and summarized by the LLM, then re-truncated to
    ``max_chars``.
    """
    text = (content or "").strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text

    # Feed the model a bounded window so the call itself stays cheap.
    window = text[: max(max_chars * 4, 8000)]
    summary = await llm.complete(
        [
            {
                "role": "system",
                "content": (
                    "Summarize the web page for research notes. Preserve key "
                    "facts, names, numbers, and claims. Be concise. Reply with "
                    "the summary only."
                ),
            },
            {
                "role": "user",
                "content": f"Title: {title}\n\nContent:\n{window}",
            },
        ],
        max_tokens=max(256, max_chars // 4),
    )
    summary = (summary or "").strip()
    if not summary:
        return text[:max_chars]
    return summary if len(summary) <= max_chars else summary[: max_chars - 1] + "…"
