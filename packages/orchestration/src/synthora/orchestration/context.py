"""Runtime research context: resolved providers, limits, and event emission.

Passed to graphs through LangGraph's ``config["configurable"]["synthora_ctx"]``
so nodes stay pure functions of (state, context) — R-ODR-6.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from synthora.core.events import ProgressEvent, RunEventType
from synthora.core.models import RunConfig, RunMetrics, SearchResult
from synthora.core.parsing import parse_json_response
from synthora.core.ports import ChatModel, EventSink, SearchEngine, SearchStrategy

__all__ = [
    "CountingChatModel",
    "CountingSearchEngine",
    "ResearchContext",
    "get_ctx",
    "parse_json_response",
]

CancelCheck = Callable[[], Awaitable[bool]]


class RunCancelledSignal(Exception):
    """Raised when cooperative cancel is observed mid-provider-call."""


class CountingChatModel:
    """Wraps a ChatModel and increments ResearchContext usage counters."""

    def __init__(self, inner: ChatModel, ctx: "ResearchContext") -> None:
        self._inner = inner
        self._ctx = ctx

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
    ) -> str:
        await self._ctx.cooperative_check()
        prompt_chars = sum(len(m.get("content") or "") for m in messages)
        result = await self._inner.complete(
            messages, temperature=temperature, max_tokens=max_tokens
        )
        self._ctx.llm_calls += 1
        self._ctx.prompt_chars += prompt_chars
        self._ctx.completion_chars += len(result or "")
        return result


class CountingSearchEngine:
    """Wraps a SearchEngine and increments ResearchContext search counters."""

    def __init__(self, inner: SearchEngine, ctx: "ResearchContext") -> None:
        self.name = getattr(inner, "name", "unknown")
        self._inner = inner
        self._ctx = ctx

    async def search(
        self, query: str, *, max_results: int = 5
    ) -> list[SearchResult]:
        await self._ctx.cooperative_check()
        self._ctx.search_calls += 1
        return await self._inner.search(query, max_results=max_results)


@dataclass
class ResearchContext:
    run_id: str
    config: RunConfig
    # role-split models (R-ODR-5)
    planner: ChatModel
    researcher: ChatModel
    compressor: ChatModel
    writer: ChatModel
    critic: ChatModel
    engines: list[SearchEngine] = field(default_factory=list)
    strategy: Optional[SearchStrategy] = None
    event_sink: Optional[EventSink] = None
    # user steering messages injected mid-run (R-STORM-6)
    steering: list[str] = field(default_factory=list)
    # MCP tools loaded from RunConfig.extra["mcp"]
    mcp_tools: list[Any] = field(default_factory=list)
    # cooperative cancel / steer drain (worker wires these)
    cancel_check: Optional[CancelCheck] = None
    drain_steering: Optional[Callable[[], Awaitable[list[str]]]] = None
    # lightweight usage counters (persisted to run_metrics)
    llm_calls: int = 0
    prompt_chars: int = 0
    completion_chars: int = 0
    search_calls: int = 0
    # models actually used when auto/fallback resolution applies
    resolved_models: dict[str, str] = field(default_factory=dict)

    async def cooperative_check(self) -> None:
        """Cancel + drain steering at provider call boundaries."""
        if self.cancel_check is not None and await self.cancel_check():
            raise RunCancelledSignal(self.run_id)
        if self.drain_steering is not None:
            for msg in await self.drain_steering():
                self.steering.append(msg)

    def wrap_providers(self) -> None:
        """Instrument LLM and search providers for metrics collection."""
        self.planner = CountingChatModel(self.planner, self)
        self.researcher = CountingChatModel(self.researcher, self)
        self.compressor = CountingChatModel(self.compressor, self)
        self.writer = CountingChatModel(self.writer, self)
        self.critic = CountingChatModel(self.critic, self)
        self.engines = [CountingSearchEngine(e, self) for e in self.engines]

    def to_metrics(self) -> RunMetrics:
        return RunMetrics(
            run_id=self.run_id,
            llm_calls=self.llm_calls,
            prompt_chars=self.prompt_chars,
            completion_chars=self.completion_chars,
            search_calls=self.search_calls,
        )

    async def emit(
        self,
        type_: RunEventType,
        message: str = "",
        *,
        node: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        if self.event_sink is None:
            return
        await self.event_sink(
            ProgressEvent(
                run_id=self.run_id,
                type=type_,
                message=message,
                node=node,
                payload=payload or {},
            )
        )


def get_ctx(config: dict) -> ResearchContext:
    ctx = config.get("configurable", {}).get("synthora_ctx")
    if ctx is None:
        raise RuntimeError(
            "ResearchContext missing: pass config={'configurable': {'synthora_ctx': ctx}}"
        )
    return ctx
