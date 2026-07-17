"""U5: pipeline registry + four pipelines golden-path with fakes."""

import json

import pytest
import synthora.orchestration.pipelines  # noqa: F401  (registers pipelines)
from synthora.core.models import RunConfig
from synthora.orchestration.registry import pipeline_registry

from tests.conftest import FakeChatModel, FakeSearchEngine
from tests.helpers import graph_config, make_ctx

SEARCH = json.dumps({"action": "search", "query": "q"})
COMPLETE = json.dumps({"action": "research_complete"})
CONDUCT = json.dumps({"action": "conduct_research", "topics": ["alpha", "beta"]})
OUTLINE = json.dumps(
    {
        "title": "Report",
        "children": [{"title": "Findings"}, {"title": "Analysis"}],
    }
)
PERSONAS = json.dumps(
    [
        {"name": "Historian", "description": "d", "focus": "f"},
        {"name": "Engineer", "description": "d", "focus": "f"},
    ]
)


def test_registry_lists_all_pipelines():
    ids = [s.id for s in pipeline_registry.list_specs()]
    assert ids == [
        "academic_research",
        "autonomous_research",
        "deep_research",
        "fast_research",
    ]
    with pytest.raises(KeyError):
        pipeline_registry.get("nope")


def test_all_pipelines_compile():
    for spec in pipeline_registry.list_specs():
        assert spec.builder() is not None


async def test_fast_research_golden_path():
    ctx = make_ctx(
        planner=FakeChatModel(default="brief text"),
        researcher=FakeChatModel(default=SEARCH),
        writer=FakeChatModel(default="# Answer\n\nfact [1]"),
        config=RunConfig(max_react_tool_calls=1),
    )
    graph = pipeline_registry.build("fast_research")
    result = await graph.ainvoke({"question": "What is X?"}, config=graph_config(ctx))
    assert result["report"].startswith("# Answer")
    assert result["citations"]


async def test_deep_research_golden_path():
    # planner: brief, supervisor conduct, supervisor complete, personas
    planner = FakeChatModel(responses=["the brief", CONDUCT, COMPLETE, PERSONAS])
    # researcher drives: researcher loop JSON, then discourse utterances
    researcher = FakeChatModel(
        responses=[SEARCH, SEARCH, json.dumps({"action": "complete"}), json.dumps({"action": "complete"})],
        default="ANSWER: insight [1]",
    )
    writer = FakeChatModel(
        responses=[OUTLINE],
        default="## Section\n\ncontent [1]",
    )
    ctx = make_ctx(
        planner=planner,
        researcher=researcher,
        writer=writer,
        critic=FakeChatModel(default="- tighten sourcing"),
        config=RunConfig(
            max_react_tool_calls=1,
            max_discourse_turns=3,
            num_perspectives=2,
        ),
    )
    graph = pipeline_registry.build("deep_research")
    result = await graph.ainvoke(
        {"question": "Deep question?"}, config=graph_config(ctx)
    )
    assert result["brief"] == "the brief"
    assert [p.name for p in result["perspectives"]] == ["Historian", "Engineer"]
    # discourse includes optional warm-start user turn + max_discourse_turns
    assert len(result["discourse"]) >= 3
    assert any(t.role == "expert" for t in result["discourse"])
    assert result["knowledge_nodes"]
    assert result["outline"].title == "Report"
    assert len(result["sections"]) == 2
    assert result["critique"]
    assert result["report"]


async def test_academic_research_verifies_and_appends_bibliography():
    planner = FakeChatModel(responses=["academic brief", "query one\nquery two"])
    critic = FakeChatModel(
        responses=[
            json.dumps({"verified": [1], "rejected": [2]}),
            "1. revise intro",
        ]
    )
    writer = FakeChatModel(responses=[OUTLINE], default="## Sec\n\ntext [1]")
    ctx = make_ctx(
        planner=planner,
        critic=critic,
        writer=writer,
        engines=[FakeSearchEngine()],
    )
    graph = pipeline_registry.build("academic_research")
    result = await graph.ainvoke(
        {"question": "Academic Q?"}, config=graph_config(ctx)
    )
    verified = {c.index: c.verified for c in result["citations"]}
    assert verified[1] is True and verified[2] is False
    assert "## Bibliography" in result["report"]
    assert "[1]" in result["report"].split("## Bibliography")[1]
    # rejected citation not in bibliography
    assert "[2]" not in result["report"].split("## Bibliography")[1]


async def test_autonomous_research_respects_cycle_bound():
    # planner drives brief, hypotheses, and the supervisor; route by system prompt
    class RoutingPlanner:
        def __init__(self):
            self.calls = []
            self.brief_done = False

        async def complete(self, messages, *, temperature=0.3, max_tokens=None):
            self.calls.append(messages)
            system = messages[0]["content"]
            if "research supervisor" in system:
                return COMPLETE
            if "research brief" in system.lower() or "Rewrite the research" in system:
                return "auto brief"
            return "hypothesis A\nhypothesis B"

    critic = FakeChatModel(default="gap one\ngap two")  # always finds gaps
    ctx = make_ctx(
        planner=RoutingPlanner(),
        critic=critic,
        config=RunConfig(max_autonomous_cycles=2, max_react_tool_calls=1),
    )
    graph = pipeline_registry.build("autonomous_research")
    result = await graph.ainvoke(
        {"question": "Explore X"}, config=graph_config(ctx)
    )
    assert result["cycle"] == 2  # bounded even though gaps appear every round
    assert result["report"]
    assert result["hypotheses"]


async def test_autonomous_stops_early_without_gaps():
    class RoutingPlanner:
        async def complete(self, messages, *, temperature=0.3, max_tokens=None):
            system = messages[0]["content"]
            if "research supervisor" in system:
                return COMPLETE
            if "Rewrite the research" in system:
                return "brief"
            return "hypothesis A"

    critic = FakeChatModel(default="")  # no gaps found
    ctx = make_ctx(
        planner=RoutingPlanner(),
        critic=critic,
        config=RunConfig(max_autonomous_cycles=5, max_react_tool_calls=1),
    )
    graph = pipeline_registry.build("autonomous_research")
    result = await graph.ainvoke({"question": "q"}, config=graph_config(ctx))
    assert result["cycle"] == 1
