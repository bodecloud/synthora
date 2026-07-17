"""Repository implementations over SQLAlchemy async sessions."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from synthora.core.events import ProgressEvent, RunEventType
from synthora.core.models import (
    Artifact,
    ArtifactKind,
    Citation,
    DiscourseTurn,
    Document,
    DocumentChunk,
    KnowledgeEdge,
    KnowledgeNode,
    NewsItem,
    NewsSubscription,
    ProviderSetting,
    ResearchRun,
    RunConfig,
    RunMetrics,
    RunStatus,
    Session,
    User,
    Workspace,
)
from synthora.persistence.database import Database
from synthora.persistence.tables import (
    ArtifactRow,
    CitationRow,
    DiscourseTurnRow,
    DocumentChunkRow,
    DocumentRow,
    KnowledgeEdgeRow,
    KnowledgeNodeRow,
    NewsItemRow,
    NewsSubscriptionRow,
    ProviderSettingRow,
    ResearchRunRow,
    RunEventRow,
    RunMetricsRow,
    SessionRow,
    UserRow,
    WorkspaceRow,
    utcnow,
)


class UserRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(self, user: User) -> User:
        async with self.db.session() as s:
            s.add(
                UserRow(
                    id=user.id,
                    username=user.username,
                    password_hash=user.password_hash,
                    created_at=user.created_at,
                )
            )
        return user

    async def get_by_username(self, username: str) -> Optional[User]:
        async with self.db.session() as s:
            row = (
                await s.execute(select(UserRow).where(UserRow.username == username))
            ).scalar_one_or_none()
        if row is None:
            return None
        return User(
            id=row.id,
            username=row.username,
            password_hash=row.password_hash,
            created_at=row.created_at,
        )


class WorkspaceRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def ensure_default(self) -> Workspace:
        """Ensure the shared anonymous workspace exists with stable id ``default``.

        Identity in ``AUTH_MODE=none`` always uses ``workspace_id="default"``,
        so the row primary key must match (not a random UUID).
        """
        async with self.db.session() as s:
            row = await s.get(WorkspaceRow, "default")
            if row is None:
                s.add(
                    WorkspaceRow(
                        id="default",
                        name="default",
                        created_at=utcnow(),
                    )
                )
                return Workspace(id="default", name="default")
            return Workspace(
                id=row.id,
                name=row.name,
                owner_id=row.owner_id,
                created_at=row.created_at,
            )

    async def ensure_for_owner(
        self, user_id: str, *, name: Optional[str] = None
    ) -> Workspace:
        """Ensure a per-user workspace whose id equals the user id (session auth)."""
        async with self.db.session() as s:
            row = await s.get(WorkspaceRow, user_id)
            if row is None:
                ws_name = name or f"user-{user_id[:8]}"
                s.add(
                    WorkspaceRow(
                        id=user_id,
                        name=ws_name,
                        owner_id=user_id,
                        created_at=utcnow(),
                    )
                )
                return Workspace(id=user_id, name=ws_name, owner_id=user_id)
            return Workspace(
                id=row.id,
                name=row.name,
                owner_id=row.owner_id,
                created_at=row.created_at,
            )


class SessionRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(self, session: Session) -> Session:
        async with self.db.session() as s:
            s.add(
                SessionRow(
                    id=session.id,
                    workspace_id=session.workspace_id,
                    title=session.title,
                    tags=session.tags,
                    created_at=session.created_at,
                )
            )
        return session

    async def list_sessions(self, workspace_id: str, limit: int = 100) -> list[Session]:
        async with self.db.session() as s:
            rows = (
                (
                    await s.execute(
                        select(SessionRow)
                        .where(SessionRow.workspace_id == workspace_id)
                        .order_by(SessionRow.created_at.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [
            Session(
                id=r.id,
                workspace_id=r.workspace_id,
                title=r.title,
                tags=list(r.tags or []),
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def get(self, session_id: str) -> Optional[Session]:
        async with self.db.session() as s:
            row = await s.get(SessionRow, session_id)
        if row is None:
            return None
        return Session(
            id=row.id,
            workspace_id=row.workspace_id,
            title=row.title,
            tags=list(row.tags or []),
            created_at=row.created_at,
        )

    async def delete(self, session_id: str) -> bool:
        async with self.db.session() as s:
            row = await s.get(SessionRow, session_id)
            if row is None:
                return False
            await s.delete(row)
        return True


def _run_from_row(row: ResearchRunRow) -> ResearchRun:
    return ResearchRun(
        id=row.id,
        session_id=row.session_id,
        workspace_id=row.workspace_id,
        question=row.question,
        brief=row.brief,
        pipeline_id=row.pipeline_id,
        status=RunStatus(row.status),
        config=RunConfig.model_validate(row.config or {}),
        error=row.error,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


class RunRepositorySQL:
    """Implements the RunRepository port over SQL."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(self, run: ResearchRun) -> ResearchRun:
        async with self.db.session() as s:
            s.add(
                ResearchRunRow(
                    id=run.id,
                    session_id=run.session_id,
                    workspace_id=run.workspace_id,
                    question=run.question,
                    brief=run.brief,
                    pipeline_id=run.pipeline_id,
                    status=run.status.value,
                    config=run.config.model_dump(mode="json"),
                    error=run.error,
                    created_at=run.created_at,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                )
            )
        return run

    async def get(self, run_id: str) -> Optional[ResearchRun]:
        async with self.db.session() as s:
            row = await s.get(ResearchRunRow, run_id)
        return _run_from_row(row) if row else None

    async def update(self, run: ResearchRun) -> ResearchRun:
        async with self.db.session() as s:
            row = await s.get(ResearchRunRow, run.id)
            if row is None:
                raise KeyError(f"run {run.id} not found")
            row.status = run.status.value
            row.brief = run.brief
            row.error = run.error
            row.session_id = run.session_id
            row.started_at = run.started_at
            row.finished_at = run.finished_at
            row.config = run.config.model_dump(mode="json")
        return run

    async def list_runs(
        self,
        *,
        workspace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[ResearchRun]:
        async with self.db.session() as s:
            q = select(ResearchRunRow).order_by(ResearchRunRow.created_at.desc()).limit(limit)
            if workspace_id:
                q = q.where(ResearchRunRow.workspace_id == workspace_id)
            if session_id:
                q = q.where(ResearchRunRow.session_id == session_id)
            rows = (await s.execute(q)).scalars().all()
        return [_run_from_row(r) for r in rows]

    async def delete(self, run_id: str) -> bool:
        async with self.db.session() as s:
            row = await s.get(ResearchRunRow, run_id)
            if row is None:
                return False
            await s.delete(row)
        return True


class EventRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def append(self, event: ProgressEvent) -> None:
        async with self.db.session() as s:
            s.add(
                RunEventRow(
                    run_id=event.run_id,
                    type=event.type.value,
                    message=event.message,
                    node=event.node,
                    payload=event.payload,
                    timestamp=event.timestamp,
                )
            )

    async def list_events(self, run_id: str, limit: int = 500) -> list[ProgressEvent]:
        async with self.db.session() as s:
            rows = (
                (
                    await s.execute(
                        select(RunEventRow)
                        .where(RunEventRow.run_id == run_id)
                        .order_by(RunEventRow.id.asc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [
            ProgressEvent(
                run_id=r.run_id,
                type=RunEventType(r.type),
                message=r.message,
                node=r.node,
                payload=r.payload or {},
                timestamp=r.timestamp,
            )
            for r in rows
        ]


class ArtifactRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def save(self, artifact: Artifact) -> Artifact:
        async with self.db.session() as s:
            s.add(
                ArtifactRow(
                    id=artifact.id,
                    run_id=artifact.run_id,
                    kind=artifact.kind.value,
                    content=artifact.content,
                    meta=artifact.metadata,
                    created_at=artifact.created_at,
                )
            )
        return artifact

    async def list_for_run(self, run_id: str) -> list[Artifact]:
        async with self.db.session() as s:
            rows = (
                (
                    await s.execute(
                        select(ArtifactRow).where(ArtifactRow.run_id == run_id)
                    )
                )
                .scalars()
                .all()
            )
        return [
            Artifact(
                id=r.id,
                run_id=r.run_id,
                kind=ArtifactKind(r.kind),
                content=r.content,
                metadata=r.meta or {},
                created_at=r.created_at,
            )
            for r in rows
        ]


class CitationRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def save_many(self, citations: list[Citation]) -> None:
        async with self.db.session() as s:
            for c in citations:
                s.add(
                    CitationRow(
                        id=c.id,
                        run_id=c.run_id,
                        url=c.url,
                        title=c.title,
                        snippet=c.snippet,
                        confidence=c.confidence,
                        index=c.index,
                        verified=c.verified,
                    )
                )

    async def list_for_run(self, run_id: str) -> list[Citation]:
        async with self.db.session() as s:
            rows = (
                (
                    await s.execute(
                        select(CitationRow).where(CitationRow.run_id == run_id)
                    )
                )
                .scalars()
                .all()
            )
        return [
            Citation(
                id=r.id,
                run_id=r.run_id,
                url=r.url,
                title=r.title,
                snippet=r.snippet,
                confidence=r.confidence,
                index=r.index,
                verified=r.verified,
            )
            for r in rows
        ]


class KnowledgeRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def save_map(
        self,
        run_id: str,
        nodes: list[KnowledgeNode],
        edges: list[KnowledgeEdge],
    ) -> None:
        async with self.db.session() as s:
            for n in nodes:
                s.add(
                    KnowledgeNodeRow(
                        id=n.id,
                        run_id=run_id,
                        name=n.name,
                        summary=n.summary,
                        parent_id=n.parent_id,
                        infos=[c.model_dump(mode="json") for c in n.infos],
                    )
                )
            for e in edges:
                s.add(
                    KnowledgeEdgeRow(
                        id=e.id,
                        run_id=run_id,
                        source_id=e.source_id,
                        target_id=e.target_id,
                        relation=e.relation,
                    )
                )

    async def load_map(
        self, run_id: str
    ) -> tuple[list[KnowledgeNode], list[KnowledgeEdge]]:
        async with self.db.session() as s:
            node_rows = (
                (
                    await s.execute(
                        select(KnowledgeNodeRow).where(
                            KnowledgeNodeRow.run_id == run_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            edge_rows = (
                (
                    await s.execute(
                        select(KnowledgeEdgeRow).where(
                            KnowledgeEdgeRow.run_id == run_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        nodes = [
            KnowledgeNode(
                id=r.id,
                run_id=r.run_id,
                name=r.name,
                summary=r.summary,
                parent_id=r.parent_id,
                infos=[Citation.model_validate(c) for c in (r.infos or [])],
            )
            for r in node_rows
        ]
        edges = [
            KnowledgeEdge(
                id=r.id,
                run_id=r.run_id,
                source_id=r.source_id,
                target_id=r.target_id,
                relation=r.relation,
            )
            for r in edge_rows
        ]
        return nodes, edges


class DiscourseRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def save_many(self, turns: list[DiscourseTurn]) -> None:
        async with self.db.session() as s:
            for t in turns:
                s.add(
                    DiscourseTurnRow(
                        id=t.id,
                        run_id=t.run_id,
                        speaker=t.speaker,
                        role=t.role,
                        utterance=t.utterance,
                        intent=t.intent,
                        citations=[c.model_dump(mode="json") for c in t.citations],
                        created_at=t.created_at,
                    )
                )

    async def list_for_run(self, run_id: str) -> list[DiscourseTurn]:
        async with self.db.session() as s:
            rows = (
                (
                    await s.execute(
                        select(DiscourseTurnRow)
                        .where(DiscourseTurnRow.run_id == run_id)
                        .order_by(DiscourseTurnRow.created_at.asc())
                    )
                )
                .scalars()
                .all()
            )
        return [
            DiscourseTurn(
                id=r.id,
                run_id=r.run_id,
                speaker=r.speaker,
                role=r.role,
                utterance=r.utterance,
                intent=r.intent,
                citations=[Citation.model_validate(c) for c in (r.citations or [])],
                created_at=r.created_at,
            )
            for r in rows
        ]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(dot / (na * nb))


def _doc_from_row(row: DocumentRow) -> Document:
    meta = dict(row.meta or {})
    content = getattr(row, "content", None) or str(meta.get("content") or "")
    return Document(
        id=row.id,
        workspace_id=row.workspace_id,
        title=row.title,
        url=row.url,
        path=row.path,
        content=content,
        meta=meta,
        created_at=row.created_at,
    )


class DocumentRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(
        self, document: Document, chunks: list[DocumentChunk] | None = None
    ) -> Document:
        meta = dict(document.meta or {})
        # Keep content in both the dedicated column and meta for older readers.
        if document.content:
            meta["content"] = document.content
        async with self.db.session() as s:
            s.add(
                DocumentRow(
                    id=document.id,
                    workspace_id=document.workspace_id,
                    title=document.title,
                    url=document.url,
                    path=document.path,
                    content=document.content or "",
                    meta=meta,
                    created_at=document.created_at,
                )
            )
            for chunk in chunks or []:
                s.add(
                    DocumentChunkRow(
                        id=chunk.id,
                        document_id=document.id,
                        workspace_id=chunk.workspace_id or document.workspace_id,
                        chunk_index=chunk.chunk_index,
                        text=chunk.text,
                        embedding=list(chunk.embedding or []),
                        meta=chunk.meta or {},
                    )
                )
        document.meta = meta
        return document

    async def list_documents(
        self, workspace_id: str, limit: int = 200
    ) -> list[Document]:
        async with self.db.session() as s:
            rows = (
                (
                    await s.execute(
                        select(DocumentRow)
                        .where(DocumentRow.workspace_id == workspace_id)
                        .order_by(DocumentRow.created_at.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [_doc_from_row(r) for r in rows]

    async def list_all_documents(self, limit: int = 5000) -> list[Document]:
        """Return documents across all workspaces (index warm / admin)."""
        async with self.db.session() as s:
            rows = (
                (
                    await s.execute(
                        select(DocumentRow)
                        .order_by(DocumentRow.created_at.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [_doc_from_row(r) for r in rows]

    async def get(self, document_id: str) -> Optional[Document]:
        async with self.db.session() as s:
            row = await s.get(DocumentRow, document_id)
        return _doc_from_row(row) if row else None

    async def delete(self, document_id: str) -> bool:
        async with self.db.session() as s:
            row = await s.get(DocumentRow, document_id)
            if row is None:
                return False
            chunks = (
                (
                    await s.execute(
                        select(DocumentChunkRow).where(
                            DocumentChunkRow.document_id == document_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            for chunk in chunks:
                await s.delete(chunk)
            await s.delete(row)
        return True

    async def list_chunks(
        self, *, workspace_id: str, document_id: Optional[str] = None
    ) -> list[DocumentChunk]:
        async with self.db.session() as s:
            q = select(DocumentChunkRow).where(
                DocumentChunkRow.workspace_id == workspace_id
            )
            if document_id:
                q = q.where(DocumentChunkRow.document_id == document_id)
            q = q.order_by(DocumentChunkRow.chunk_index.asc())
            rows = (await s.execute(q)).scalars().all()
        return [
            DocumentChunk(
                id=r.id,
                document_id=r.document_id,
                workspace_id=r.workspace_id,
                chunk_index=r.chunk_index,
                text=r.text,
                embedding=list(r.embedding or []),
                meta=r.meta or {},
            )
            for r in rows
        ]

    async def search(
        self,
        workspace_id: str,
        *,
        query: str = "",
        query_embedding: Optional[list[float]] = None,
        max_results: int = 5,
    ) -> list[dict]:
        """Return scored chunk hits (embedding cosine, with text fallback)."""
        chunks = await self.list_chunks(workspace_id=workspace_id)
        docs = {d.id: d for d in await self.list_documents(workspace_id)}
        scored: list[tuple[float, DocumentChunk, Document]] = []
        q = (query or "").lower().strip()
        for chunk in chunks:
            doc = docs.get(chunk.document_id)
            if doc is None:
                continue
            score = 0.0
            if query_embedding and chunk.embedding:
                score = _cosine(query_embedding, chunk.embedding)
            if q:
                hay = f"{doc.title}\n{chunk.text}".lower()
                if q in hay:
                    score = max(score, 0.85 if q in doc.title.lower() else 0.55)
            if score > 0:
                scored.append((score, chunk, doc))
        scored.sort(key=lambda t: t[0], reverse=True)
        results: list[dict] = []
        for score, chunk, doc in scored[:max_results]:
            results.append(
                {
                    "document_id": doc.id,
                    "chunk_id": chunk.id,
                    "title": doc.title,
                    "url": doc.url or f"collection://{doc.id}",
                    "snippet": chunk.text[:500],
                    "content": chunk.text,
                    "score": score,
                    "chunk_index": chunk.chunk_index,
                }
            )
        return results


class ProviderSettingsRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def list_settings(self, workspace_id: str) -> list[ProviderSetting]:
        async with self.db.session() as s:
            rows = (
                (
                    await s.execute(
                        select(ProviderSettingRow).where(
                            ProviderSettingRow.workspace_id == workspace_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        return [
            ProviderSetting(
                id=r.id,
                workspace_id=r.workspace_id,
                key=r.key,
                value=dict(r.value or {}),
            )
            for r in rows
        ]

    async def get(self, workspace_id: str, key: str) -> Optional[ProviderSetting]:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(ProviderSettingRow).where(
                        ProviderSettingRow.workspace_id == workspace_id,
                        ProviderSettingRow.key == key,
                    )
                )
            ).scalar_one_or_none()
        if row is None:
            return None
        return ProviderSetting(
            id=row.id,
            workspace_id=row.workspace_id,
            key=row.key,
            value=dict(row.value or {}),
        )

    async def upsert(
        self, workspace_id: str, key: str, value: dict
    ) -> ProviderSetting:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(ProviderSettingRow).where(
                        ProviderSettingRow.workspace_id == workspace_id,
                        ProviderSettingRow.key == key,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                setting = ProviderSetting(
                    workspace_id=workspace_id, key=key, value=value
                )
                s.add(
                    ProviderSettingRow(
                        id=setting.id,
                        workspace_id=workspace_id,
                        key=key,
                        value=value,
                    )
                )
                return setting
            row.value = value
            return ProviderSetting(
                id=row.id,
                workspace_id=row.workspace_id,
                key=row.key,
                value=dict(value),
            )


class NewsRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create_subscription(self, sub: NewsSubscription) -> NewsSubscription:
        async with self.db.session() as s:
            s.add(
                NewsSubscriptionRow(
                    id=sub.id,
                    workspace_id=sub.workspace_id,
                    query=sub.query,
                    cadence=sub.cadence,
                    last_run_at=sub.last_run_at,
                    created_at=sub.created_at,
                )
            )
        return sub

    async def get_subscription(self, sub_id: str) -> Optional[NewsSubscription]:
        async with self.db.session() as s:
            row = await s.get(NewsSubscriptionRow, sub_id)
        if row is None:
            return None
        return NewsSubscription(
            id=row.id,
            workspace_id=row.workspace_id,
            query=row.query,
            cadence=row.cadence,
            last_run_at=row.last_run_at,
            created_at=row.created_at,
        )

    async def list_subscriptions(
        self, workspace_id: str, limit: int = 100
    ) -> list[NewsSubscription]:
        async with self.db.session() as s:
            rows = (
                (
                    await s.execute(
                        select(NewsSubscriptionRow)
                        .where(NewsSubscriptionRow.workspace_id == workspace_id)
                        .order_by(NewsSubscriptionRow.created_at.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [
            NewsSubscription(
                id=r.id,
                workspace_id=r.workspace_id,
                query=r.query,
                cadence=r.cadence,
                last_run_at=r.last_run_at,
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def update_subscription(self, sub: NewsSubscription) -> NewsSubscription:
        async with self.db.session() as s:
            row = await s.get(NewsSubscriptionRow, sub.id)
            if row is None:
                raise KeyError(f"subscription {sub.id} not found")
            row.query = sub.query
            row.cadence = sub.cadence
            row.last_run_at = sub.last_run_at
        return sub

    async def delete_subscription(self, sub_id: str) -> bool:
        async with self.db.session() as s:
            row = await s.get(NewsSubscriptionRow, sub_id)
            if row is None:
                return False
            items = (
                (
                    await s.execute(
                        select(NewsItemRow).where(NewsItemRow.subscription_id == sub_id)
                    )
                )
                .scalars()
                .all()
            )
            for item in items:
                await s.delete(item)
            await s.delete(row)
        return True

    async def add_items(self, items: list[NewsItem]) -> None:
        if not items:
            return
        async with self.db.session() as s:
            for item in items:
                s.add(
                    NewsItemRow(
                        id=item.id,
                        subscription_id=item.subscription_id,
                        title=item.title,
                        url=item.url,
                        summary=item.summary,
                        created_at=item.created_at,
                    )
                )

    async def list_items(
        self,
        *,
        workspace_id: Optional[str] = None,
        subscription_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[NewsItem]:
        """List news items, always scoped by workspace when provided (no IDOR)."""
        async with self.db.session() as s:
            q = (
                select(NewsItemRow)
                .join(
                    NewsSubscriptionRow,
                    NewsItemRow.subscription_id == NewsSubscriptionRow.id,
                )
                .order_by(NewsItemRow.created_at.desc())
                .limit(limit)
            )
            if workspace_id:
                q = q.where(NewsSubscriptionRow.workspace_id == workspace_id)
            if subscription_id:
                q = q.where(NewsItemRow.subscription_id == subscription_id)
            rows = (await s.execute(q)).scalars().all()
        return [
            NewsItem(
                id=r.id,
                subscription_id=r.subscription_id,
                title=r.title,
                url=r.url,
                summary=r.summary,
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def list_due_subscriptions(self) -> list[NewsSubscription]:
        """Return subscriptions whose cadence interval has elapsed."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        intervals = {
            "hourly": timedelta(hours=1),
            "daily": timedelta(days=1),
            "weekly": timedelta(weeks=1),
        }
        async with self.db.session() as s:
            rows = (await s.execute(select(NewsSubscriptionRow))).scalars().all()
        due: list[NewsSubscription] = []
        for row in rows:
            interval = intervals.get(row.cadence.lower(), timedelta(days=1))
            last = row.last_run_at
            if last is not None and last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if last is None or (now - last) >= interval:
                due.append(
                    NewsSubscription(
                        id=row.id,
                        workspace_id=row.workspace_id,
                        query=row.query,
                        cadence=row.cadence,
                        last_run_at=row.last_run_at,
                        created_at=row.created_at,
                    )
                )
        return due


class MetricsRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def save(self, metrics: RunMetrics) -> RunMetrics:
        async with self.db.session() as s:
            existing = await s.get(RunMetricsRow, metrics.run_id)
            if existing is None:
                s.add(
                    RunMetricsRow(
                        run_id=metrics.run_id,
                        llm_calls=metrics.llm_calls,
                        prompt_chars=metrics.prompt_chars,
                        completion_chars=metrics.completion_chars,
                        search_calls=metrics.search_calls,
                        created_at=metrics.created_at,
                    )
                )
            else:
                existing.llm_calls = metrics.llm_calls
                existing.prompt_chars = metrics.prompt_chars
                existing.completion_chars = metrics.completion_chars
                existing.search_calls = metrics.search_calls
        return metrics

    async def get(self, run_id: str) -> Optional[RunMetrics]:
        async with self.db.session() as s:
            row = await s.get(RunMetricsRow, run_id)
        if row is None:
            return None
        return RunMetrics(
            run_id=row.run_id,
            llm_calls=row.llm_calls,
            prompt_chars=row.prompt_chars,
            completion_chars=row.completion_chars,
            search_calls=row.search_calls,
            created_at=row.created_at,
        )

    async def summary(self, *, workspace_id: Optional[str] = None) -> dict:
        """Aggregate metrics across runs (optionally scoped to a workspace)."""
        from sqlalchemy import func

        async with self.db.session() as s:
            q = select(
                func.count(RunMetricsRow.run_id),
                func.coalesce(func.sum(RunMetricsRow.llm_calls), 0),
                func.coalesce(func.sum(RunMetricsRow.prompt_chars), 0),
                func.coalesce(func.sum(RunMetricsRow.completion_chars), 0),
                func.coalesce(func.sum(RunMetricsRow.search_calls), 0),
            )
            if workspace_id:
                q = q.join(
                    ResearchRunRow, RunMetricsRow.run_id == ResearchRunRow.id
                ).where(ResearchRunRow.workspace_id == workspace_id)
            row = (await s.execute(q)).one()
        return {
            "runs": int(row[0] or 0),
            "llm_calls": int(row[1] or 0),
            "prompt_chars": int(row[2] or 0),
            "completion_chars": int(row[3] or 0),
            "search_calls": int(row[4] or 0),
        }
