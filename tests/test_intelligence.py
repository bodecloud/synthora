"""U4: STORM/Co-STORM intelligence — perspectives, knowledge map, discourse, outline."""

import json

from synthora.core.models import Citation, Perspective, SearchResult
from synthora.intelligence.discourse import DiscourseManager, rank_unused_evidence
from synthora.intelligence.knowledge_map import KnowledgeMap, jaccard
from synthora.intelligence.outline import (
    OutlineBuilder,
    SectionWriter,
    flatten_sections,
    outline_to_markdown,
)
from synthora.intelligence.perspectives import PerspectiveEngine

from tests.conftest import FakeChatModel, FakeSearchEngine

# ---------------------------------------------------------------- perspectives


async def test_perspective_discovery_parses_personas():
    llm = FakeChatModel(
        responses=[
            json.dumps(
                [
                    {"name": "Historian", "description": "d", "focus": "origins"},
                    {"name": "Engineer", "description": "d", "focus": "implementation"},
                    {"name": "Skeptic", "description": "d", "focus": "limitations"},
                ]
            )
        ]
    )
    engine = PerspectiveEngine(llm)
    perspectives = await engine.discover("topic brief", count=3)
    assert [p.name for p in perspectives] == ["Historian", "Engineer", "Skeptic"]


async def test_perspective_discovery_fallback_on_garbage():
    engine = PerspectiveEngine(FakeChatModel(default="not json at all"))
    perspectives = await engine.discover("brief", count=2)
    assert len(perspectives) == 2


async def test_perspective_questions():
    llm = FakeChatModel(responses=["Why X?\nHow Y?\nWhat Z?"])
    engine = PerspectiveEngine(llm)
    persona = Perspective(name="Historian", description="d", focus="f")
    questions = await engine.generate_questions(persona, "brief", count=3)
    assert questions == ["Why X?", "How Y?", "What Z?"]


# ---------------------------------------------------------------- knowledge map


def _cite(title: str, snippet: str = "") -> Citation:
    return Citation(url=f"https://x.com/{title.replace(' ', '-')}", title=title, snippet=snippet)


def test_knowledge_map_insert_places_by_similarity():
    kmap = KnowledgeMap("Quantum computing")
    qec = kmap.add_node("Error correction codes")
    hw = kmap.add_node("Hardware platforms")
    target = kmap.insert(_cite("surface code error correction threshold"))
    assert target.id == qec.id
    target2 = kmap.insert(_cite("superconducting hardware platforms qubits"))
    assert target2.id == hw.id


async def test_knowledge_map_reorganize_splits_over_capacity():
    kmap = KnowledgeMap("Root", capacity=3)
    node = kmap.add_node("Big topic")
    for i in range(5):
        node.infos.append(_cite(f"info {i}"))
    llm = FakeChatModel(
        responses=[
            json.dumps(
                [
                    {"name": "Subtopic A", "indices": [0, 1, 2]},
                    {"name": "Subtopic B", "indices": [3, 4]},
                ]
            )
        ]
    )
    created = await kmap.reorganize(llm)
    assert {n.name for n in created} == {"Subtopic A", "Subtopic B"}
    assert len(node.infos) == 0
    a = next(n for n in created if n.name == "Subtopic A")
    assert len(a.infos) == 3
    # hierarchy edges recorded
    assert any(e.source_id == node.id for e in kmap.edges)


async def test_knowledge_map_reorganize_skips_under_capacity():
    kmap = KnowledgeMap("Root", capacity=10)
    node = kmap.add_node("Small")
    node.infos.append(_cite("only one"))
    created = await kmap.reorganize(FakeChatModel())
    assert created == []


# ---------------------------------------------------------------- discourse


def test_moderator_ranking_prefers_relevant_but_novel():
    topic = "quantum error correction codes"
    discussion = "we discussed surface codes and stabilizer measurements"
    unused = [
        SearchResult(url="https://a", title="surface codes stabilizer", snippet="surface codes stabilizer measurements discussed"),
        SearchResult(url="https://b", title="quantum error correction hardware decoder", snippet="novel decoder hardware for quantum error correction codes"),
        SearchResult(url="https://c", title="cooking recipes", snippet="pasta with tomatoes"),
    ]
    ranked = rank_unused_evidence(unused, topic=topic, discussion=discussion)
    assert ranked[0][0].url == "https://b"  # relevant AND undiscussed wins


async def test_discourse_turn_policy_moderator_after_l_experts():
    experts = [
        Perspective(name="A", description="", focus=""),
        Perspective(name="B", description="", focus=""),
    ]
    llm = FakeChatModel(default="ANSWER: grounded insight [1]")
    manager = DiscourseManager(llm, engines=[FakeSearchEngine()], experts_per_round=2)
    turns = await manager.run_discourse("topic", experts, max_turns=6)
    roles = [t.role for t in turns]
    assert roles[:3] == ["expert", "expert", "moderator"]
    assert roles[3:6] == ["expert", "expert", "moderator"]


async def test_expert_answer_attaches_citations():
    experts = [Perspective(name="A", description="", focus="")]
    llm = FakeChatModel(default="ANSWER: fact [1] supported")
    manager = DiscourseManager(llm, engines=[FakeSearchEngine()], experts_per_round=1)
    turn = await manager.expert_turn(experts[0], "topic")
    assert turn.intent == "answer"
    assert turn.citations and turn.citations[0].url == "https://example.com/a"


async def test_user_steering_injection():
    manager = DiscourseManager(FakeChatModel())
    turn = manager.inject_user_turn("focus on cost")
    assert turn.role == "user" and manager.turns == [turn]


# ---------------------------------------------------------------- outline


async def test_outline_builder_parses_structure():
    llm = FakeChatModel(
        responses=[
            json.dumps(
                {
                    "title": "Report",
                    "children": [
                        {"title": "Background", "children": []},
                        {"title": "Findings", "children": [{"title": "Detail"}]},
                    ],
                }
            )
        ]
    )
    outline = await OutlineBuilder(llm).build("brief")
    assert outline.title == "Report"
    assert [s.title for s in flatten_sections(outline)] == ["Background", "Findings"]
    md = outline_to_markdown(outline)
    assert "# Report" in md and "### Detail" in md


async def test_outline_links_knowledge_nodes():
    kmap = KnowledgeMap("Root")
    kmap.add_node("Error correction")
    llm = FakeChatModel(
        responses=[
            json.dumps(
                {"title": "R", "children": [{"title": "Error correction methods"}]}
            )
        ]
    )
    outline = await OutlineBuilder(llm).build("brief", knowledge_map=kmap)
    section = flatten_sections(outline)[0]
    assert section.knowledge_node_ids


async def test_section_writer_offers_relevant_citations():
    citations = [
        Citation(url="https://a", title="error correction methods", snippet="s", index=1),
        Citation(url="https://b", title="unrelated cooking", snippet="s", index=2),
    ]
    llm = FakeChatModel(default="## Section\n\nText [1].")
    writer = SectionWriter(llm)
    from synthora.core.models import OutlineNode

    text = await writer.write_section(
        OutlineNode(title="error correction methods"),
        brief="b",
        citations=citations,
    )
    assert text.startswith("## Section")
    # relevant citation [1] listed before unrelated [2] in the prompt
    prompt = llm.calls[0][1]["content"]
    assert prompt.index("[1]") < prompt.index("[2]")


def test_jaccard_bounds():
    assert jaccard("", "anything") == 0.0
    assert jaccard("alpha beta", "alpha beta") == 1.0


# ---------------------------------------------------------------- embeddings / wiki / co-storm


def test_hash_embedding_similarity_ranks_related_higher():
    from synthora.intelligence.embeddings import (
        cosine_similarity,
        default_hash_embeddings,
        make_embedding_similarity,
    )

    emb = default_hash_embeddings()
    encode = emb.embed_one if hasattr(emb, "embed_one") else emb._one
    a = encode("quantum error correction codes")
    b = encode("quantum error correction threshold")
    c = encode("pasta cooking recipes tomatoes")
    assert cosine_similarity(a, b) > cosine_similarity(a, c)

    sim = make_embedding_similarity(emb)
    assert sim(
        "quantum error correction codes",
        "quantum error correction threshold",
    ) > sim(
        "quantum error correction codes",
        "pasta cooking recipes tomatoes",
    )
    # SimilarityFn plugs into KnowledgeMap without error
    kmap = KnowledgeMap("Root", similarity=sim)
    kmap.add_node("quantum error correction")
    placed = kmap.insert(_cite("surface code quantum error correction"))
    assert placed is not None


async def test_mine_from_wikipedia_toc_uses_sections(monkeypatch):
    llm = FakeChatModel(
        responses=[
            json.dumps(
                [
                    {"name": "Historian", "description": "d", "focus": "History"},
                    {"name": "Engineer", "description": "d", "focus": "Applications"},
                ]
            )
        ]
    )
    engine = PerspectiveEngine(llm)

    async def fake_toc(self, topic, *, lang="en", timeout=20.0):
        return ["History", "Applications", "Criticism"]

    monkeypatch.setattr(PerspectiveEngine, "_fetch_wikipedia_toc", fake_toc)
    perspectives = await engine.mine_from_wikipedia_toc("quantum computing", count=2)
    assert [p.name for p in perspectives] == ["Historian", "Engineer"]
    # LLM prompt included TOC context
    user_msg = llm.calls[0][1]["content"]
    assert "History" in user_msg and "Applications" in user_msg


async def test_mine_from_wikipedia_toc_falls_back_when_empty(monkeypatch):
    llm = FakeChatModel(
        responses=[
            json.dumps([{"name": "Fallback Expert", "description": "d", "focus": "f"}])
        ]
    )
    engine = PerspectiveEngine(llm)

    async def empty_toc(self, topic, *, lang="en", timeout=20.0):
        return []

    monkeypatch.setattr(PerspectiveEngine, "_fetch_wikipedia_toc", empty_toc)
    perspectives = await engine.mine_from_wikipedia_toc("obscure topic", count=1)
    assert perspectives[0].name == "Fallback Expert"


async def test_section_writer_prefers_embedding_cosine():
    from synthora.core.models import OutlineNode
    from synthora.intelligence.embeddings import HashEmbeddings

    citations = [
        Citation(
            url="https://a",
            title="quantum error correction codes",
            snippet="stabilizer codes",
            index=1,
        ),
        Citation(
            url="https://b",
            title="unrelated cooking pasta",
            snippet="tomato sauce",
            index=2,
        ),
    ]
    llm = FakeChatModel(default="## Section\n\nText [1].")
    writer = SectionWriter(llm, embeddings=HashEmbeddings())
    await writer.write_section(
        OutlineNode(title="quantum error correction"),
        brief="b",
        citations=citations,
    )
    prompt = llm.calls[0][1]["content"]
    assert prompt.index("[1]") < prompt.index("[2]")


async def test_warm_start_returns_outline_questions():
    llm = FakeChatModel(responses=["What is X?\nHow does Y work?\nWhy Z matters?"])
    manager = DiscourseManager(llm)
    experts = [Perspective(name="A", description="d", focus="origins")]
    questions = await manager.warm_start("topic", experts)
    assert questions == ["What is X?", "How does Y work?", "Why Z matters?"]
    assert manager.turns == []  # warm_start does not append turns


async def test_pure_rag_turn_answers_from_evidence():
    llm = FakeChatModel(default="ANSWER: grounded claim [1]")
    manager = DiscourseManager(llm)
    manager.add_evidence(
        [
            SearchResult(
                url="https://e.com",
                title="Evidence",
                snippet="fact",
                content="fact detail",
            )
        ]
    )
    turn = await manager.pure_rag_turn("topic")
    assert turn.role == "rag" and turn.speaker == "PureRAG"
    assert turn.intent == "answer"
    assert turn.citations and turn.citations[0].url == "https://e.com"


async def test_simulated_user_turn_asks_followup():
    llm = FakeChatModel(default="What about edge cases?")
    manager = DiscourseManager(llm)
    manager.inject_user_turn("prior steer")
    turn = await manager.simulated_user_turn("topic")
    assert turn.role == "user" and turn.intent == "question"
    assert "edge cases" in turn.utterance
    assert manager.turns[-1] is turn



async def test_bibliography_includes_authors_and_year():
    from synthora.orchestration.intelligence_nodes import bibliography_node

    from tests.helpers import graph_config, make_ctx

    ctx = make_ctx()
    state = {
        "report": "# Draft",
        "citations": [
            Citation(
                url="https://ex/a",
                title="Paper A",
                index=1,
                verified=True,
                metadata={"authors": ["Ada Lovelace", "Alan Turing"], "year": 1936},
            )
        ],
    }
    out = await bibliography_node(state, graph_config(ctx))
    assert "Ada Lovelace" in out["report"]
    assert "(1936)" in out["report"]
