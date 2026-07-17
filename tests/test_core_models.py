"""U1: domain model round-trips."""

from synthora.core.events import ProgressEvent, RunEventType
from synthora.core.models import (
    Citation,
    KnowledgeNode,
    OutlineNode,
    ResearchRun,
    RunConfig,
    RunStatus,
)


def test_run_config_defaults():
    cfg = RunConfig()
    assert cfg.pipeline_id == "deep_research"
    assert cfg.max_concurrent_research_units == 5
    assert cfg.max_researcher_iterations == 6
    assert cfg.num_perspectives == 3
    assert cfg.moderator_alpha == 0.5


def test_research_run_roundtrip():
    run = ResearchRun(question="What is quantum error correction?")
    data = run.model_dump(mode="json")
    restored = ResearchRun.model_validate(data)
    assert restored.id == run.id
    assert restored.status == RunStatus.QUEUED
    assert restored.config.pipeline_id == "deep_research"


def test_outline_recursion():
    outline = OutlineNode(
        title="Root",
        children=[OutlineNode(title="Child", children=[OutlineNode(title="Leaf")])],
    )
    data = outline.model_dump()
    restored = OutlineNode.model_validate(data)
    assert restored.children[0].children[0].title == "Leaf"


def test_knowledge_node_holds_citations():
    node = KnowledgeNode(
        name="Surface codes",
        infos=[Citation(url="https://arxiv.org/abs/xxxx", title="Surface code paper")],
    )
    assert node.infos[0].confidence == 1.0


def test_progress_event_wire_format():
    ev = ProgressEvent(run_id="abc", type=RunEventType.NODE_STARTED, node="brief")
    wire = ev.to_wire()
    assert wire["type"] == "node_started"
    assert wire["run_id"] == "abc"
    assert "timestamp" in wire
