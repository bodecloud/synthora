"""U1: repository round-trips against in-memory SQLite."""

from synthora.core.events import ProgressEvent, RunEventType
from synthora.core.models import (
    Artifact,
    ArtifactKind,
    Citation,
    KnowledgeEdge,
    KnowledgeNode,
    ResearchRun,
    RunStatus,
    Session,
    User,
)
from synthora.persistence import (
    ArtifactRepository,
    CitationRepository,
    EventRepository,
    KnowledgeRepository,
    RunRepositorySQL,
    SessionRepository,
    UserRepository,
    WorkspaceRepository,
)


async def test_workspace_default(db):
    repo = WorkspaceRepository(db)
    ws1 = await repo.ensure_default()
    ws2 = await repo.ensure_default()
    assert ws1.id == ws2.id == "default"


async def test_workspace_for_owner(db):
    repo = WorkspaceRepository(db)
    ws = await repo.ensure_for_owner("user-abc", name="alice")
    again = await repo.ensure_for_owner("user-abc")
    assert ws.id == again.id == "user-abc"
    assert ws.owner_id == "user-abc"


async def test_user_roundtrip(db):
    repo = UserRepository(db)
    await repo.create(User(username="alice", password_hash="x"))
    got = await repo.get_by_username("alice")
    assert got is not None and got.username == "alice"
    assert await repo.get_by_username("nobody") is None


async def test_run_lifecycle(db):
    ws = await WorkspaceRepository(db).ensure_default()
    sessions = SessionRepository(db)
    session = await sessions.create(Session(workspace_id=ws.id, title="QEC"))

    runs = RunRepositorySQL(db)
    run = ResearchRun(
        question="What is QEC?", session_id=session.id, workspace_id=ws.id
    )
    await runs.create(run)

    run.status = RunStatus.RUNNING
    run.brief = "Investigate quantum error correction"
    await runs.update(run)

    got = await runs.get(run.id)
    assert got.status == RunStatus.RUNNING
    assert got.brief.startswith("Investigate")

    listed = await runs.list_runs(workspace_id=ws.id)
    assert [r.id for r in listed] == [run.id]


async def test_events_append_and_replay(db):
    ws = await WorkspaceRepository(db).ensure_default()
    runs = RunRepositorySQL(db)
    run = await runs.create(ResearchRun(question="q", workspace_id=ws.id))

    events = EventRepository(db)
    await events.append(
        ProgressEvent(run_id=run.id, type=RunEventType.NODE_STARTED, node="brief")
    )
    await events.append(
        ProgressEvent(run_id=run.id, type=RunEventType.DONE, message="finished")
    )
    replay = await events.list_events(run.id)
    assert [e.type for e in replay] == [RunEventType.NODE_STARTED, RunEventType.DONE]


async def test_artifacts_citations_knowledge(db):
    ws = await WorkspaceRepository(db).ensure_default()
    runs = RunRepositorySQL(db)
    run = await runs.create(ResearchRun(question="q", workspace_id=ws.id))

    artifacts = ArtifactRepository(db)
    await artifacts.save(
        Artifact(run_id=run.id, kind=ArtifactKind.REPORT_MARKDOWN, content="# Report")
    )
    assert (await artifacts.list_for_run(run.id))[0].content == "# Report"

    citations = CitationRepository(db)
    await citations.save_many(
        [Citation(run_id=run.id, url="https://example.com", index=1)]
    )
    assert (await citations.list_for_run(run.id))[0].index == 1

    knowledge = KnowledgeRepository(db)
    root = KnowledgeNode(name="Root topic")
    child = KnowledgeNode(name="Subtopic", parent_id=root.id)
    edge = KnowledgeEdge(source_id=root.id, target_id=child.id, relation="parent_of")
    await knowledge.save_map(run.id, [root, child], [edge])
    nodes, edges = await knowledge.load_map(run.id)
    assert {n.name for n in nodes} == {"Root topic", "Subtopic"}
    assert edges[0].relation == "parent_of"
