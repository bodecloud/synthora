"""Extra platform API routes: documents, settings, news, metrics, chat, MCP.

Mounted via ``app.include_router(extra_router)`` from ``main``.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from synthora.adapters.document_index import document_index
from synthora.adapters.embeddings import HashEmbeddings, OpenAIEmbeddings
from synthora.api.auth import current_identity
from synthora.api.settings import settings
from synthora.core.models import (
    ArtifactKind,
    Document,
    DocumentChunk,
    NewsSubscription,
    ResearchRun,
    RunConfig,
    RunStatus,
    Session,
)
from synthora.orchestration.registry import pipeline_registry
from synthora.persistence import (
    ArtifactRepository,
    DocumentRepository,
    MetricsRepository,
    NewsRepository,
    ProviderSettingsRepository,
    RunRepositorySQL,
    SessionRepository,
)
from synthora.persistence.database import Database
from synthora.worker.queue import RedisJobQueue

extra_router = APIRouter()


# ---------------------------------------------------------------- schemas


class FollowupRequest(BaseModel):
    question: str = Field(min_length=3)
    pipeline_id: Optional[str] = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: Optional[str] = None


class NewsSubscriptionCreate(BaseModel):
    query: str = Field(min_length=2)
    cadence: str = "daily"


class NewsSubscriptionUpdate(BaseModel):
    query: Optional[str] = None
    cadence: Optional[str] = None


class CreateDocumentRequest(BaseModel):
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    url: Optional[str] = None


class DocumentSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    max_results: int = Field(default=5, ge=1, le=50)


class ProviderSettingPut(BaseModel):
    value: dict = Field(default_factory=dict)


class McpToolCallRequest(BaseModel):
    name: str = Field(min_length=1)
    arguments: dict = Field(default_factory=dict)


# ---------------------------------------------------------------- helpers


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_queue(request: Request) -> RedisJobQueue:
    return request.app.state.queue


def _chunk_text(text: str, size: int = 500) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    return [text[i : i + size] for i in range(0, len(text), size)]


def _embedding_model():
    from synthora.adapters.embeddings import resolve_default_embeddings

    return resolve_default_embeddings()


async def _get_run_checked(
    run_id: str, identity: dict, db: Database
) -> ResearchRun:
    run = await RunRepositorySQL(db).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if settings.auth_mode == "session" and run.workspace_id != identity["workspace_id"]:
        raise HTTPException(status_code=404, detail="run not found")
    return run


def _sub_to_dict(sub: NewsSubscription) -> dict:
    return {
        "id": sub.id,
        "workspace_id": sub.workspace_id,
        "query": sub.query,
        "cadence": sub.cadence,
        "last_run_at": sub.last_run_at.isoformat() if sub.last_run_at else None,
        "created_at": sub.created_at.isoformat(),
    }


# ---------------------------------------------------------------- follow-up


@extra_router.post("/api/v1/research/{run_id}/followup", status_code=202)
async def followup_research(
    run_id: str,
    body: FollowupRequest,
    request: Request,
    identity: dict = Depends(current_identity),
) -> dict:
    """Start a follow-up run linked to the same session as ``run_id``."""
    db = get_db(request)
    queue = get_queue(request)
    parent = await _get_run_checked(run_id, identity, db)
    pipeline_id = body.pipeline_id or parent.pipeline_id
    try:
        pipeline_registry.get(pipeline_id)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    session_id = parent.session_id
    if not session_id:
        session = Session(
            workspace_id=identity["workspace_id"],
            title=f"Follow-up: {parent.question[:80]}",
        )
        await SessionRepository(db).create(session)
        session_id = session.id
        parent.session_id = session_id
        await RunRepositorySQL(db).update(parent)

    artifacts = await ArtifactRepository(db).list_for_run(run_id)
    notes_snip = ""
    for art in artifacts:
        if art.kind == ArtifactKind.RAW_NOTES and art.content:
            notes_snip = art.content[:2000]
            break
    brief_snip = (parent.brief or "")[:2000]
    if not brief_snip:
        report = next(
            (a for a in artifacts if a.kind == ArtifactKind.REPORT_MARKDOWN), None
        )
        if report:
            brief_snip = report.content[:2000]

    parent_cfg = parent.config.model_dump(mode="json")
    extra = dict(parent_cfg.get("extra") or {})
    extra.update(
        {
            "parent_run_id": parent.id,
            "parent_brief": brief_snip,
            "parent_notes_snippet": notes_snip,
        }
    )
    parent_cfg["extra"] = extra
    parent_cfg["pipeline_id"] = pipeline_id
    config = RunConfig.model_validate(parent_cfg)
    run = ResearchRun(
        question=body.question,
        pipeline_id=pipeline_id,
        workspace_id=identity["workspace_id"],
        session_id=session_id,
        config=config,
    )
    await RunRepositorySQL(db).create(run)
    await queue.enqueue(run.id, {"pipeline_id": run.pipeline_id})
    return {
        "run_id": run.id,
        "status": run.status.value,
        "session_id": run.session_id,
        "parent_run_id": parent.id,
    }


@extra_router.get("/api/v1/research/{run_id}/metrics")
async def get_run_metrics(
    run_id: str,
    request: Request,
    identity: dict = Depends(current_identity),
) -> dict:
    db = get_db(request)
    await _get_run_checked(run_id, identity, db)
    metrics = await MetricsRepository(db).get(run_id)
    if metrics is None:
        raise HTTPException(status_code=404, detail="metrics not found")
    return metrics.model_dump(mode="json")


# ---------------------------------------------------------------- chat


@extra_router.post("/api/v1/chat", status_code=202)
async def chat(
    body: ChatRequest,
    request: Request,
    identity: dict = Depends(current_identity),
) -> dict:
    """Minimal chat mode: enqueue a ``fast_research`` run for the message."""
    db = get_db(request)
    queue = get_queue(request)
    pipeline_id = "fast_research"
    try:
        pipeline_registry.get(pipeline_id)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    session_id = body.session_id
    if session_id:
        session = await SessionRepository(db).get(session_id)
        if session is None or (
            settings.auth_mode == "session"
            and session.workspace_id != identity["workspace_id"]
        ):
            raise HTTPException(status_code=404, detail="session not found")
    else:
        session = Session(
            workspace_id=identity["workspace_id"],
            title=f"Chat: {body.message[:60]}",
            tags=["chat"],
        )
        await SessionRepository(db).create(session)
        session_id = session.id

    config = RunConfig(pipeline_id=pipeline_id, extra={"chat": True})
    # Load prior completed reports in this session so the brief has chat memory.
    if session_id:
        prior = await RunRepositorySQL(db).list_runs(
            workspace_id=identity["workspace_id"],
            session_id=session_id,
            limit=8,
        )
        history_bits: list[str] = []
        for prev in reversed(prior):
            if prev.status != RunStatus.COMPLETED:
                continue
            arts = await ArtifactRepository(db).list_for_run(prev.id)
            report = next(
                (a for a in arts if a.kind == ArtifactKind.REPORT_MARKDOWN), None
            )
            snippet = (report.content if report else prev.brief or "")[:1200]
            if not snippet:
                continue
            history_bits.append(
                f"User: {prev.question}\nAssistant (excerpt): {snippet}"
            )
        if history_bits:
            config.extra["chat_history"] = "\n\n".join(history_bits[-5:])
    run = ResearchRun(
        question=body.message,
        pipeline_id=pipeline_id,
        workspace_id=identity["workspace_id"],
        session_id=session_id,
        config=config,
    )
    await RunRepositorySQL(db).create(run)
    await queue.enqueue(run.id, {"pipeline_id": run.pipeline_id})
    return {
        "run_id": run.id,
        "status": run.status.value,
        "session_id": session_id,
    }


# ---------------------------------------------------------------- news


@extra_router.post("/api/v1/news/subscriptions", status_code=201)
async def create_news_subscription(
    body: NewsSubscriptionCreate,
    request: Request,
    identity: dict = Depends(current_identity),
) -> dict:
    cadence = body.cadence.lower().strip()
    if cadence not in ("hourly", "daily", "weekly"):
        raise HTTPException(
            status_code=422, detail="cadence must be hourly, daily, or weekly"
        )
    sub = NewsSubscription(
        workspace_id=identity["workspace_id"],
        query=body.query.strip(),
        cadence=cadence,
    )
    await NewsRepository(get_db(request)).create_subscription(sub)
    return _sub_to_dict(sub)


@extra_router.get("/api/v1/news/subscriptions")
async def list_news_subscriptions(
    request: Request,
    identity: dict = Depends(current_identity),
) -> dict:
    subs = await NewsRepository(get_db(request)).list_subscriptions(
        identity["workspace_id"]
    )
    return {"subscriptions": [_sub_to_dict(s) for s in subs]}


@extra_router.get("/api/v1/news/subscriptions/{sub_id}")
async def get_news_subscription(
    sub_id: str,
    request: Request,
    identity: dict = Depends(current_identity),
) -> dict:
    sub = await NewsRepository(get_db(request)).get_subscription(sub_id)
    if sub is None or (
        settings.auth_mode == "session"
        and sub.workspace_id != identity["workspace_id"]
    ):
        raise HTTPException(status_code=404, detail="subscription not found")
    return _sub_to_dict(sub)


@extra_router.patch("/api/v1/news/subscriptions/{sub_id}")
async def update_news_subscription(
    sub_id: str,
    body: NewsSubscriptionUpdate,
    request: Request,
    identity: dict = Depends(current_identity),
) -> dict:
    repo = NewsRepository(get_db(request))
    sub = await repo.get_subscription(sub_id)
    if sub is None or (
        settings.auth_mode == "session"
        and sub.workspace_id != identity["workspace_id"]
    ):
        raise HTTPException(status_code=404, detail="subscription not found")
    if body.query is not None:
        sub.query = body.query.strip()
    if body.cadence is not None:
        cadence = body.cadence.lower().strip()
        if cadence not in ("hourly", "daily", "weekly"):
            raise HTTPException(
                status_code=422, detail="cadence must be hourly, daily, or weekly"
            )
        sub.cadence = cadence
    await repo.update_subscription(sub)
    return _sub_to_dict(sub)


@extra_router.delete("/api/v1/news/subscriptions/{sub_id}")
async def delete_news_subscription(
    sub_id: str,
    request: Request,
    identity: dict = Depends(current_identity),
) -> dict:
    repo = NewsRepository(get_db(request))
    sub = await repo.get_subscription(sub_id)
    if sub is None or (
        settings.auth_mode == "session"
        and sub.workspace_id != identity["workspace_id"]
    ):
        raise HTTPException(status_code=404, detail="subscription not found")
    await repo.delete_subscription(sub_id)
    return {"deleted": True, "id": sub_id}


@extra_router.get("/api/v1/news/items")
async def list_news_items(
    request: Request,
    subscription_id: Optional[str] = None,
    identity: dict = Depends(current_identity),
) -> dict:
    items = await NewsRepository(get_db(request)).list_items(
        workspace_id=identity["workspace_id"],
        subscription_id=subscription_id,
    )
    return {
        "items": [
            {
                "id": i.id,
                "subscription_id": i.subscription_id,
                "title": i.title,
                "url": i.url,
                "summary": i.summary,
                "created_at": i.created_at.isoformat(),
            }
            for i in items
        ]
    }


@extra_router.post("/api/v1/news/subscriptions/{sub_id}/fetch")
async def fetch_news_subscription(
    sub_id: str,
    request: Request,
    identity: dict = Depends(current_identity),
) -> dict:
    from synthora.worker.news import fetch_subscription_news

    repo = NewsRepository(get_db(request))
    sub = await repo.get_subscription(sub_id)
    if sub is None or (
        settings.auth_mode == "session"
        and sub.workspace_id != identity["workspace_id"]
    ):
        raise HTTPException(status_code=404, detail="subscription not found")
    items = await fetch_subscription_news(repo, sub)
    return {
        "subscription_id": sub_id,
        "fetched": len(items),
        "items": [
            {
                "id": i.id,
                "title": i.title,
                "url": i.url,
                "summary": i.summary,
                "created_at": i.created_at.isoformat(),
            }
            for i in items
        ],
    }


# ---------------------------------------------------------------- metrics summary


@extra_router.get("/api/v1/metrics/summary")
async def metrics_summary(
    request: Request, identity: dict = Depends(current_identity)
) -> dict:
    return await MetricsRepository(get_db(request)).summary(
        workspace_id=identity["workspace_id"]
    )


# ---------------------------------------------------------------- documents (RAG)


@extra_router.post("/api/v1/documents", status_code=201)
async def create_document(
    body: CreateDocumentRequest,
    request: Request,
    identity: dict = Depends(current_identity),
) -> dict:
    db = get_db(request)
    workspace_id = identity["workspace_id"]
    pieces = _chunk_text(body.content, 500)
    embedder = _embedding_model()
    vectors = await embedder.embed(pieces) if pieces else []
    doc = Document(
        workspace_id=workspace_id,
        title=body.title,
        url=body.url,
        content=body.content,
        meta={"content": body.content, "chunk_count": len(pieces)},
    )
    chunks = [
        DocumentChunk(
            document_id=doc.id,
            workspace_id=workspace_id,
            chunk_index=i,
            text=text,
            embedding=vectors[i] if i < len(vectors) else [],
        )
        for i, text in enumerate(pieces)
    ]
    await DocumentRepository(db).create(doc, chunks)
    document_index.upsert_document(
        workspace_id,
        {
            "id": doc.id,
            "title": doc.title,
            "url": doc.url,
            "content": doc.content,
        },
        [
            {
                "chunk_index": c.chunk_index,
                "text": c.text,
                "embedding": c.embedding,
            }
            for c in chunks
        ],
    )
    return {
        "id": doc.id,
        "title": doc.title,
        "url": doc.url,
        "workspace_id": doc.workspace_id,
        "chunk_count": len(chunks),
        "created_at": doc.created_at.isoformat(),
    }


@extra_router.get("/api/v1/documents")
async def list_documents(
    request: Request, identity: dict = Depends(current_identity)
) -> dict:
    docs = await DocumentRepository(get_db(request)).list_documents(
        identity["workspace_id"]
    )
    return {
        "documents": [
            {
                "id": d.id,
                "title": d.title,
                "url": d.url,
                "workspace_id": d.workspace_id,
                "created_at": d.created_at.isoformat(),
                "content_preview": (d.content or "")[:200],
            }
            for d in docs
        ]
    }


@extra_router.delete("/api/v1/documents/{document_id}")
async def delete_document(
    document_id: str,
    request: Request,
    identity: dict = Depends(current_identity),
) -> dict:
    repo = DocumentRepository(get_db(request))
    doc = await repo.get(document_id)
    if doc is None or (
        settings.auth_mode == "session"
        and doc.workspace_id != identity["workspace_id"]
    ):
        raise HTTPException(status_code=404, detail="document not found")
    await repo.delete(document_id)
    document_index.remove(identity["workspace_id"], document_id)
    return {"deleted": True, "id": document_id}


@extra_router.post("/api/v1/documents/search")
async def search_documents(
    body: DocumentSearchRequest,
    request: Request,
    identity: dict = Depends(current_identity),
) -> dict:
    workspace_id = identity["workspace_id"]
    embedder = _embedding_model()
    query_vec = (await embedder.embed([body.query]))[0]
    hits = await DocumentRepository(get_db(request)).search(
        workspace_id,
        query=body.query,
        query_embedding=query_vec,
        max_results=body.max_results,
    )
    if not hits:
        indexed = document_index.search(
            workspace_id,
            body.query,
            query_embedding=query_vec,
            max_results=body.max_results,
        )
        hits = [
            {
                "document_id": (r.metadata or {}).get("document_id"),
                "title": r.title,
                "url": r.url,
                "snippet": r.snippet,
                "content": r.content,
                "score": r.score,
            }
            for r in indexed
        ]
    return {"results": hits, "query": body.query}


# ---------------------------------------------------------------- provider settings


_SECRET_VALUE_FIELDS = frozenset(
    {"api_key", "key", "token", "password", "secret", "access_token"}
)


def _redact_setting_value(value: dict) -> dict:
    """Mask secret fields in API responses (storage remains plaintext in DB)."""
    out: dict = {}
    for k, v in (value or {}).items():
        if str(k).lower() in _SECRET_VALUE_FIELDS and v:
            out[k] = "***"
        else:
            out[k] = v
    return out


def _merge_setting_value(existing: dict | None, incoming: dict) -> dict:
    """Merge PUT payload; ignore masked placeholders so secrets are not clobbered."""
    merged = dict(existing or {})
    for k, v in (incoming or {}).items():
        if (
            str(k).lower() in _SECRET_VALUE_FIELDS
            and isinstance(v, str)
            and v.strip() in ("", "***", "********")
        ):
            continue
        merged[k] = v
    return merged


@extra_router.get("/api/v1/settings")
async def list_settings(
    request: Request, identity: dict = Depends(current_identity)
) -> dict:
    rows = await ProviderSettingsRepository(get_db(request)).list_settings(
        identity["workspace_id"]
    )
    return {
        "settings": [
            {
                "key": r.key,
                "value": _redact_setting_value(r.value or {}),
                "workspace_id": r.workspace_id,
            }
            for r in rows
        ]
    }


@extra_router.get("/api/v1/settings/{key}")
async def get_setting(
    key: str,
    request: Request,
    identity: dict = Depends(current_identity),
) -> dict:
    row = await ProviderSettingsRepository(get_db(request)).get(
        identity["workspace_id"], key
    )
    if row is None:
        raise HTTPException(status_code=404, detail="setting not found")
    return {
        "key": row.key,
        "value": _redact_setting_value(row.value or {}),
        "workspace_id": row.workspace_id,
    }


@extra_router.put("/api/v1/settings/{key}")
async def put_setting(
    key: str,
    body: ProviderSettingPut,
    request: Request,
    identity: dict = Depends(current_identity),
) -> dict:
    repo = ProviderSettingsRepository(get_db(request))
    existing = await repo.get(identity["workspace_id"], key)
    merged = _merge_setting_value(
        existing.value if existing else None, body.value or {}
    )
    row = await repo.upsert(identity["workspace_id"], key, merged)
    return {
        "key": row.key,
        "value": _redact_setting_value(row.value or {}),
        "workspace_id": row.workspace_id,
    }


# ---------------------------------------------------------------- MCP tools (REST)


@extra_router.post("/api/v1/mcp/tools/list")
async def mcp_tools_list(
    identity: dict = Depends(current_identity),
) -> dict:
    return {
        "tools": [
            {
                "name": "start_research",
                "description": (
                    "Start a research run. Args: question, pipeline_id optional."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "pipeline_id": {"type": "string"},
                    },
                    "required": ["question"],
                },
            },
            {
                "name": "get_run_status",
                "description": "Get status for a research run. Args: run_id.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"run_id": {"type": "string"}},
                    "required": ["run_id"],
                },
            },
            {
                "name": "get_report",
                "description": (
                    "Fetch the markdown report for a completed run. Args: run_id."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {"run_id": {"type": "string"}},
                    "required": ["run_id"],
                },
            },
            {
                "name": "search_documents",
                "description": (
                    "Search the workspace document library. Args: query, max_results."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            },
        ]
    }


@extra_router.post("/api/v1/mcp/tools/call")
async def mcp_tools_call(
    body: McpToolCallRequest,
    request: Request,
    identity: dict = Depends(current_identity),
) -> dict:
    db = get_db(request)
    queue = get_queue(request)
    name = body.name
    args = body.arguments or {}
    if name == "start_research":
        question = str(args.get("question") or "").strip()
        if len(question) < 3:
            raise HTTPException(status_code=422, detail="question required")
        pipeline_id = str(args.get("pipeline_id") or "fast_research")
        try:
            pipeline_registry.get(pipeline_id)
        except KeyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        config = RunConfig.model_validate(
            {**(args.get("config") or {}), "pipeline_id": pipeline_id}
        )
        run = ResearchRun(
            question=question,
            pipeline_id=pipeline_id,
            workspace_id=identity["workspace_id"],
            config=config,
        )
        await RunRepositorySQL(db).create(run)
        await queue.enqueue(run.id, {"pipeline_id": run.pipeline_id})
        return {
            "content": json.dumps(
                {"run_id": run.id, "status": run.status.value}
            )
        }
    if name == "get_run_status":
        run_id = str(args.get("run_id") or "")
        run = await _get_run_checked(run_id, identity, db)
        return {
            "content": json.dumps(
                {"run_id": run.id, "status": run.status.value, "error": run.error}
            )
        }
    if name == "get_report":
        run_id = str(args.get("run_id") or "")
        await _get_run_checked(run_id, identity, db)
        artifacts = await ArtifactRepository(db).list_for_run(run_id)
        report = next(
            (a for a in artifacts if a.kind == ArtifactKind.REPORT_MARKDOWN), None
        )
        if report is None:
            raise HTTPException(status_code=404, detail="report not ready")
        return {"content": report.content}
    if name == "search_documents":
        query = str(args.get("query") or "")
        max_results = int(args.get("max_results") or 5)
        embedder = _embedding_model()
        query_vec = (await embedder.embed([query]))[0] if query else []
        hits = await DocumentRepository(db).search(
            identity["workspace_id"],
            query=query,
            query_embedding=query_vec or None,
            max_results=max_results,
        )
        return {"content": json.dumps({"results": hits})}
    raise HTTPException(status_code=404, detail=f"unknown tool: {name}")
