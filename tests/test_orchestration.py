"""U3: ODR-style orchestration — researcher loop, supervisor loop, core graph."""

import json

from synthora.core.models import RunConfig
from synthora.orchestration.context import parse_json_response
from synthora.orchestration.graphs import (
    build_deep_researcher_core,
    build_researcher_graph,
    build_supervisor_graph,
)

from tests.conftest import FakeChatModel, FakeSearchEngine
from tests.helpers import graph_config, make_ctx


def test_parse_json_response_variants():
    assert parse_json_response('{"a": 1}') == {"a": 1}
    assert parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_response('Sure! Here it is: {"a": {"b": 2}} hope that helps') == {
        "a": {"b": 2}
    }
    assert parse_json_response("no json here") is None


def test_graphs_compile():
    from synthora.orchestration.checkpoint import get_checkpointer

    assert build_researcher_graph() is not None
    assert build_supervisor_graph() is not None
    assert build_deep_researcher_core().compile(checkpointer=get_checkpointer()) is not None


async def test_clarify_interrupt_and_resume():
    from langgraph.types import Command
    from synthora.orchestration.checkpoint import get_checkpointer

    planner = FakeChatModel(
        responses=[
            '{"clear": false, "question": "Which aspect of X?"}',
            "Detailed research brief about X.",
            json.dumps({"action": "research_complete", "reason": "done"}),
        ]
    )
    researcher = FakeChatModel(
        responses=[
            json.dumps({"action": "complete", "reflection": "done"}),
        ]
    )
    ctx = make_ctx(
        planner=planner,
        researcher=researcher,
        config=RunConfig(allow_clarification=True, max_react_tool_calls=1),
        run_id="clarify-run-1",
    )
    graph = build_deep_researcher_core().compile(checkpointer=get_checkpointer())
    cfg = graph_config(ctx)
    paused = await graph.ainvoke({"question": "Tell me about X"}, config=cfg)
    assert "__interrupt__" in paused
    resumed = await graph.ainvoke(Command(resume="Focus on history"), config=cfg)
    assert resumed.get("clarification") == "Focus on history"
    assert "brief" in resumed and resumed["brief"]
    assert resumed.get("report")


async def test_researcher_loop_searches_then_completes():
    researcher = FakeChatModel(
        responses=[
            json.dumps({"action": "search", "query": "sub question", "reflection": "start"}),
            json.dumps({"action": "complete", "reflection": "enough"}),
        ]
    )
    compressor = FakeChatModel(default="dense compressed notes")
    engine = FakeSearchEngine()
    ctx = make_ctx(researcher=researcher, compressor=compressor, engines=[engine])
    graph = build_researcher_graph()
    result = await graph.ainvoke(
        {"topic": "test topic", "tool_calls": 0}, config=graph_config(ctx)
    )
    assert engine.queries == ["sub question"]
    assert result["compressed"] == "dense compressed notes"
    assert result["findings"]


async def test_researcher_respects_tool_call_budget():
    always_search = FakeChatModel(
        default=json.dumps({"action": "search", "query": "again"})
    )
    ctx = make_ctx(
        researcher=always_search,
        config=RunConfig(max_react_tool_calls=3),
    )
    graph = build_researcher_graph()
    result = await graph.ainvoke(
        {"topic": "t", "tool_calls": 0}, config=graph_config(ctx)
    )
    assert result["tool_calls"] == 3


async def test_supervisor_delegates_then_completes():
    planner = FakeChatModel(
        responses=[
            json.dumps({"action": "conduct_research", "topics": ["topic A", "topic B"]}),
            json.dumps({"action": "research_complete", "reason": "covered"}),
        ]
    )
    researcher = FakeChatModel(
        default=json.dumps({"action": "search", "query": "q"})
    )
    ctx = make_ctx(
        planner=planner,
        researcher=researcher,
        config=RunConfig(max_react_tool_calls=1),
    )
    graph = build_supervisor_graph()
    result = await graph.ainvoke(
        {"brief": "research brief", "research_iterations": 0},
        config=graph_config(ctx),
    )
    notes = result.get("notes", [])
    assert any("topic A" in n for n in notes)
    assert any("topic B" in n for n in notes)
    assert result["sources"]


async def test_supervisor_concurrency_overflow_reports_error():
    planner = FakeChatModel(
        responses=[
            json.dumps(
                {"action": "conduct_research", "topics": ["t1", "t2", "t3"]}
            ),
            json.dumps({"action": "research_complete"}),
        ]
    )
    ctx = make_ctx(
        planner=planner,
        researcher=FakeChatModel(default=json.dumps({"action": "search", "query": "q"})),
        config=RunConfig(max_concurrent_research_units=2, max_react_tool_calls=1),
    )
    graph = build_supervisor_graph()
    result = await graph.ainvoke(
        {"brief": "b", "research_iterations": 0}, config=graph_config(ctx)
    )
    assert any("capacity error" in n and "t3" in n for n in result["notes"])


async def test_supervisor_iteration_cap():
    keep_going = FakeChatModel(
        default=json.dumps({"action": "conduct_research", "topics": ["t"]})
    )
    ctx = make_ctx(
        planner=keep_going,
        researcher=FakeChatModel(default=json.dumps({"action": "search", "query": "q"})),
        config=RunConfig(max_researcher_iterations=2, max_react_tool_calls=1),
    )
    graph = build_supervisor_graph()
    result = await graph.ainvoke(
        {"brief": "b", "research_iterations": 0}, config=graph_config(ctx)
    )
    assert result["research_iterations"] <= 3  # cap + final routing check


async def test_deep_researcher_core_end_to_end():
    planner = FakeChatModel(
        responses=[
            "A precise research brief.",
            json.dumps({"action": "conduct_research", "topics": ["alpha"]}),
            json.dumps({"action": "research_complete"}),
        ]
    )
    writer = FakeChatModel(default="# Final Report\n\nFindings [1].\n\n## Sources")
    ctx = make_ctx(
        planner=planner,
        researcher=FakeChatModel(default=json.dumps({"action": "search", "query": "q"})),
        writer=writer,
        config=RunConfig(max_react_tool_calls=1, allow_clarification=False),
    )
    graph = build_deep_researcher_core().compile()
    result = await graph.ainvoke(
        {"question": "What is X?"}, config=graph_config(ctx)
    )
    assert result["brief"] == "A precise research brief."
    assert result["report"].startswith("# Final Report")
    assert result["citations"]
    assert result["citations"][0].index == 1
