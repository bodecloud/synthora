"""Test helpers for orchestration tests: context builders."""

from __future__ import annotations

from synthora.core.models import RunConfig
from synthora.orchestration.context import ResearchContext

from tests.conftest import FakeChatModel, FakeSearchEngine


def make_ctx(
    *,
    planner: FakeChatModel | None = None,
    researcher: FakeChatModel | None = None,
    compressor: FakeChatModel | None = None,
    writer: FakeChatModel | None = None,
    critic: FakeChatModel | None = None,
    engines: list | None = None,
    config: RunConfig | None = None,
    run_id: str | None = None,
) -> ResearchContext:
    import uuid

    default = FakeChatModel()
    return ResearchContext(
        run_id=run_id or f"test-{uuid.uuid4().hex[:12]}",
        config=config or RunConfig(),
        planner=planner or default,
        researcher=researcher or default,
        compressor=compressor or FakeChatModel(default="compressed notes"),
        writer=writer or FakeChatModel(default="# Report\n\ncontent [1]"),
        critic=critic or FakeChatModel(default="Looks good."),
        engines=engines if engines is not None else [FakeSearchEngine()],
        strategy=None,
    )


def graph_config(ctx: ResearchContext, *, thread_id: str | None = None) -> dict:
    return {
        "configurable": {
            "synthora_ctx": ctx,
            "thread_id": thread_id or ctx.run_id,
        },
        "recursion_limit": 100,
    }
