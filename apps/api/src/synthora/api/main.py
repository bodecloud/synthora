"""Synthora API gateway (R-LDR-3): REST + WebSocket + optional auth."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Optional

import redis.asyncio as aioredis
import synthora.orchestration.pipelines  # noqa: F401  (registers pipelines)
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from synthora.adapters import llm_registry, search_engine_registry, strategy_registry
from synthora.api.auth import (
    current_identity,
    hash_password,
    issue_token,
    verify_password,
)
from synthora.api.routes_extra import extra_router
from synthora.api.settings import settings
from synthora.core.events import ProgressEvent, RunEventType
from synthora.core.models import (
    Artifact,
    ArtifactKind,
    ResearchRun,
    RunConfig,
    RunStatus,
    Session,
    User,
)
from synthora.orchestration.registry import pipeline_registry
from synthora.persistence import (
    ArtifactRepository,
    CitationRepository,
    DiscourseRepository,
    EventRepository,
    KnowledgeRepository,
    RunRepositorySQL,
    SessionRepository,
    UserRepository,
    WorkspaceRepository,
)
from synthora.persistence.database import Database
from synthora.worker.queue import RedisJobQueue, events_channel


@asynccontextmanager
async def lifespan(app: FastAPI):
    from synthora.adapters.document_index import warm_document_index_from_db
    from synthora.orchestration.checkpoint import ensure_checkpointer

    settings.assert_secure_for_auth()
    db = Database(settings.database_url)
    await db.ensure_schema()
    await ensure_checkpointer()
    redis = aioredis.from_url(settings.redis_url)
    app.state.db = db
    app.state.redis = redis
    app.state.queue = RedisJobQueue(redis)
    await WorkspaceRepository(db).ensure_default()
    try:
        n = await warm_document_index_from_db(db)
        logger = logging.getLogger("synthora.api")
        logger.info("document index warmed with %d document(s)", n)
    except Exception:
        logging.getLogger("synthora.api").exception(
            "document index warm-up failed; collection RAG may be empty"
        )
    yield
    await redis.aclose()
    await db.dispose()


app = FastAPI(title="Synthora", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(extra_router)


def get_db() -> Database:
    return app.state.db


def get_queue() -> RedisJobQueue:
    return app.state.queue


# ---------------------------------------------------------------- schemas


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    username: str
    password: str


class StartResearchRequest(BaseModel):
    question: str = Field(min_length=3)
    pipeline_id: str = "deep_research"
    session_id: Optional[str] = None
    config: Optional[dict] = None


class SteerRequest(BaseModel):
    message: str = Field(min_length=1)


class ResumeRequest(BaseModel):
    answer: str = Field(min_length=1)


class CreateSessionRequest(BaseModel):
    title: str = "Untitled research"
    tags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- health


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict:
    try:
        await app.state.redis.ping()
        async with app.state.db.session() as _:
            pass
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ready"}


# ---------------------------------------------------------------- auth


@app.post("/api/v1/auth/register", status_code=201)
async def register(body: RegisterRequest) -> dict:
    if settings.auth_mode != "session":
        raise HTTPException(status_code=400, detail="auth disabled (AUTH_MODE=none)")
    if not settings.allow_registrations:
        raise HTTPException(status_code=403, detail="registrations disabled")
    users = UserRepository(get_db())
    if await users.get_by_username(body.username):
        raise HTTPException(status_code=409, detail="username taken")
    user = User(username=body.username, password_hash=hash_password(body.password))
    await users.create(user)
    await WorkspaceRepository(get_db()).ensure_for_owner(
        user.id, name=user.username
    )
    return {"token": issue_token(user), "user_id": user.id}


@app.post("/api/v1/auth/login")
async def login(body: LoginRequest) -> dict:
    if settings.auth_mode != "session":
        raise HTTPException(status_code=400, detail="auth disabled (AUTH_MODE=none)")
    users = UserRepository(get_db())
    user = await users.get_by_username(body.username)
    if user is None or not verify_password(body.password, user.password_hash or ""):
        raise HTTPException(status_code=401, detail="invalid credentials")
    return {"token": issue_token(user), "user_id": user.id}


# ---------------------------------------------------------------- sessions


@app.post("/api/v1/sessions", status_code=201)
async def create_session(
    body: CreateSessionRequest, identity: dict = Depends(current_identity)
) -> dict:
    session = Session(
        workspace_id=identity["workspace_id"],
        title=body.title,
        tags=body.tags,
    )
    await SessionRepository(get_db()).create(session)
    return {
        "id": session.id,
        "title": session.title,
        "tags": session.tags,
        "workspace_id": session.workspace_id,
        "created_at": session.created_at.isoformat(),
    }


@app.get("/api/v1/sessions")
async def list_sessions(identity: dict = Depends(current_identity)) -> dict:
    sessions = await SessionRepository(get_db()).list_sessions(
        identity["workspace_id"]
    )
    return {
        "sessions": [
            {
                "id": s.id,
                "title": s.title,
                "tags": s.tags,
                "workspace_id": s.workspace_id,
                "created_at": s.created_at.isoformat(),
            }
            for s in sessions
        ]
    }


@app.get("/api/v1/sessions/{session_id}")
async def get_session(
    session_id: str, identity: dict = Depends(current_identity)
) -> dict:
    session = await SessionRepository(get_db()).get(session_id)
    if session is None or (
        settings.auth_mode == "session"
        and session.workspace_id != identity["workspace_id"]
    ):
        raise HTTPException(status_code=404, detail="session not found")
    runs = await RunRepositorySQL(get_db()).list_runs(
        workspace_id=identity["workspace_id"], session_id=session_id
    )
    return {
        "id": session.id,
        "title": session.title,
        "tags": session.tags,
        "workspace_id": session.workspace_id,
        "created_at": session.created_at.isoformat(),
        "runs": [
            {
                "id": r.id,
                "question": r.question,
                "pipeline_id": r.pipeline_id,
                "status": r.status.value,
                "created_at": r.created_at.isoformat(),
            }
            for r in runs
        ],
    }


@app.delete("/api/v1/sessions/{session_id}")
async def delete_session(
    session_id: str, identity: dict = Depends(current_identity)
) -> dict:
    session = await SessionRepository(get_db()).get(session_id)
    if session is None or (
        settings.auth_mode == "session"
        and session.workspace_id != identity["workspace_id"]
    ):
        raise HTTPException(status_code=404, detail="session not found")
    await SessionRepository(get_db()).delete(session_id)
    return {"deleted": True, "id": session_id}


# ---------------------------------------------------------------- research


@app.post("/api/v1/research", status_code=202)
async def start_research(
    body: StartResearchRequest, identity: dict = Depends(current_identity)
) -> dict:
    try:
        pipeline_registry.get(body.pipeline_id)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.session_id:
        session = await SessionRepository(get_db()).get(body.session_id)
        if session is None or (
            settings.auth_mode == "session"
            and session.workspace_id != identity["workspace_id"]
        ):
            raise HTTPException(status_code=404, detail="session not found")
    config = RunConfig.model_validate(
        {**(body.config or {}), "pipeline_id": body.pipeline_id}
    )
    run = ResearchRun(
        question=body.question,
        pipeline_id=body.pipeline_id,
        workspace_id=identity["workspace_id"],
        session_id=body.session_id,
        config=config,
    )
    await RunRepositorySQL(get_db()).create(run)
    await get_queue().enqueue(run.id, {"pipeline_id": run.pipeline_id})
    return {"run_id": run.id, "status": run.status.value, "session_id": run.session_id}


@app.get("/api/v1/research")
async def list_research(
    session_id: Optional[str] = None,
    identity: dict = Depends(current_identity),
) -> dict:
    runs = await RunRepositorySQL(get_db()).list_runs(
        workspace_id=identity["workspace_id"], session_id=session_id
    )
    return {
        "runs": [
            {
                "id": r.id,
                "question": r.question,
                "pipeline_id": r.pipeline_id,
                "session_id": r.session_id,
                "status": r.status.value,
                "created_at": r.created_at.isoformat(),
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in runs
        ]
    }


async def _get_run_checked(run_id: str, identity: dict) -> ResearchRun:
    run = await RunRepositorySQL(get_db()).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if settings.auth_mode == "session" and run.workspace_id != identity["workspace_id"]:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@app.get("/api/v1/research/{run_id}")
async def get_research(
    run_id: str, identity: dict = Depends(current_identity)
) -> dict:
    run = await _get_run_checked(run_id, identity)
    return {
        "id": run.id,
        "question": run.question,
        "brief": run.brief,
        "pipeline_id": run.pipeline_id,
        "session_id": run.session_id,
        "status": run.status.value,
        "error": run.error,
        "config": run.config.model_dump(mode="json"),
        "created_at": run.created_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


@app.delete("/api/v1/research/{run_id}")
async def delete_research(
    run_id: str, identity: dict = Depends(current_identity)
) -> dict:
    await _get_run_checked(run_id, identity)
    await RunRepositorySQL(get_db()).delete(run_id)
    return {"deleted": True, "id": run_id}


@app.post("/api/v1/research/clear")
async def clear_research(identity: dict = Depends(current_identity)) -> dict:
    runs = await RunRepositorySQL(get_db()).list_runs(
        workspace_id=identity["workspace_id"], limit=1000
    )
    deleted = 0
    for run in runs:
        if await RunRepositorySQL(get_db()).delete(run.id):
            deleted += 1
    return {"deleted": deleted}


@app.post("/api/v1/research/{run_id}/cancel")
async def cancel_research(
    run_id: str, identity: dict = Depends(current_identity)
) -> dict:
    run = await _get_run_checked(run_id, identity)
    if run.status in (
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    ):
        raise HTTPException(status_code=409, detail=f"run already {run.status.value}")
    await get_queue().request_cancel(run_id)
    # Reflect cancel immediately so UI does not stay stuck on "running".
    if run.status in (RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.AWAITING_INPUT):
        run.status = RunStatus.CANCELLED
        from datetime import datetime, timezone

        run.finished_at = datetime.now(timezone.utc)
        run.error = "cancelled by user"
        await RunRepositorySQL(get_db()).update(run)
        event = ProgressEvent(
            run_id=run.id,
            type=RunEventType.STATUS,
            message="cancelled",
            payload={"status": "cancelled"},
        )
        await EventRepository(get_db()).append(event)
        await get_queue().publish_event(run.id, event.to_wire())
    return {"run_id": run_id, "cancel_requested": True, "status": "cancelled"}


@app.post("/api/v1/research/{run_id}/resume", status_code=202)
async def resume_research(
    run_id: str, body: ResumeRequest, identity: dict = Depends(current_identity)
) -> dict:
    run = await _get_run_checked(run_id, identity)
    if run.status != RunStatus.AWAITING_INPUT:
        raise HTTPException(
            status_code=409,
            detail=f"run is {run.status.value}, expected awaiting_input",
        )
    run.status = RunStatus.QUEUED
    run.error = None
    await RunRepositorySQL(get_db()).update(run)
    await get_queue().enqueue(
        run_id, {"pipeline_id": run.pipeline_id, "resume_value": body.answer}
    )
    return {"run_id": run_id, "status": "queued", "resumed": True}


@app.post("/api/v1/research/{run_id}/steer")
async def steer_research(
    run_id: str, body: SteerRequest, identity: dict = Depends(current_identity)
) -> dict:
    run = await _get_run_checked(run_id, identity)
    if run.status not in (RunStatus.QUEUED, RunStatus.RUNNING):
        raise HTTPException(
            status_code=409,
            detail=f"run is {run.status.value}, expected queued or running",
        )
    await get_queue().push_steering(run_id, body.message)
    return {"run_id": run_id, "steered": True}


@app.get("/api/v1/research/{run_id}/report")
async def get_report(
    run_id: str, identity: dict = Depends(current_identity)
) -> dict:
    run = await _get_run_checked(run_id, identity)
    artifacts = await ArtifactRepository(get_db()).list_for_run(run_id)
    report = next(
        (a for a in artifacts if a.kind == ArtifactKind.REPORT_MARKDOWN), None
    )
    if report is None:
        raise HTTPException(status_code=404, detail="report not ready")
    citations = await CitationRepository(get_db()).list_for_run(run_id)
    return {
        "run_id": run_id,
        "status": run.status.value,
        "report_markdown": report.content,
        "citations": [c.model_dump(mode="json") for c in citations],
        "artifacts": [
            {"id": a.id, "kind": a.kind.value} for a in artifacts
        ],
    }


@app.get("/api/v1/research/{run_id}/export")
async def export_report(
    run_id: str,
    format: str = "markdown",
    identity: dict = Depends(current_identity),
):
    """Export the report as a downloadable file (R-LDR-5).

    ``format=markdown`` / ``html`` / ``pdf``.
    """
    import base64

    from fastapi.responses import Response
    from synthora.api.export import markdown_to_pdf_bytes, render_html_document

    run = await _get_run_checked(run_id, identity)
    artifacts = await ArtifactRepository(get_db()).list_for_run(run_id)
    report = next(
        (a for a in artifacts if a.kind == ArtifactKind.REPORT_MARKDOWN), None
    )
    if report is None:
        raise HTTPException(status_code=404, detail="report not ready")
    if format == "markdown":
        return Response(
            content=report.content,
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'attachment; filename="synthora-{run_id}.md"'
            },
        )
    if format == "html":
        return Response(
            content=render_html_document(report.content, title=run.question),
            media_type="text/html",
            headers={
                "Content-Disposition": f'attachment; filename="synthora-{run_id}.html"'
            },
        )
    if format == "pdf":
        pdf_bytes = markdown_to_pdf_bytes(report.content, title=run.question)
        await ArtifactRepository(get_db()).save(
            Artifact(
                run_id=run_id,
                kind=ArtifactKind.EXPORT_PDF,
                content=base64.b64encode(pdf_bytes).decode("ascii"),
                metadata={"bytes": len(pdf_bytes), "title": run.question},
            )
        )
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="synthora-{run_id}.pdf"'
            },
        )
    raise HTTPException(
        status_code=422, detail="format must be markdown, html, or pdf"
    )


@app.get("/api/v1/research/{run_id}/knowledge-map")
async def get_knowledge_map(
    run_id: str, identity: dict = Depends(current_identity)
) -> dict:
    await _get_run_checked(run_id, identity)
    nodes, edges = await KnowledgeRepository(get_db()).load_map(run_id)
    return {
        "nodes": [n.model_dump(mode="json") for n in nodes],
        "edges": [e.model_dump(mode="json") for e in edges],
    }


@app.get("/api/v1/research/{run_id}/discourse")
async def get_discourse(
    run_id: str, identity: dict = Depends(current_identity)
) -> dict:
    await _get_run_checked(run_id, identity)
    turns = await DiscourseRepository(get_db()).list_for_run(run_id)
    return {"turns": [t.model_dump(mode="json") for t in turns]}


@app.get("/api/v1/research/{run_id}/events")
async def get_events(
    run_id: str, identity: dict = Depends(current_identity)
) -> dict:
    await _get_run_checked(run_id, identity)
    events = await EventRepository(get_db()).list_events(run_id)
    return {"events": [e.to_wire() for e in events]}

# ---------------------------------------------------------------- catalog


@app.get("/api/v1/pipelines")
async def list_pipelines() -> dict:
    return {
        "pipelines": [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "tags": s.tags,
            }
            for s in pipeline_registry.list_specs()
        ]
    }


@app.get("/api/v1/providers")
async def list_providers() -> dict:
    return {
        "llm_providers": llm_registry.providers(),
        "search_engines": search_engine_registry.engines(),
        "search_strategies": strategy_registry.strategies(),
    }


# ---------------------------------------------------------------- websocket


@app.websocket("/api/v1/research/{run_id}/events/ws")
async def events_ws(
    websocket: WebSocket, run_id: str, token: Optional[str] = None
) -> None:
    """Replay persisted events, then stream live ones from Redis pub/sub.

    Under ``AUTH_MODE=session``, clients must pass ``?token=<jwt>`` (browsers
    cannot set Authorization on WebSocket). The run must belong to the
    caller's workspace.
    """
    from synthora.api.auth import identity_from_token

    try:
        # Prefer query token; fall back to Authorization header if present.
        auth_header = websocket.headers.get("authorization") or ""
        bearer = (
            auth_header.removeprefix("Bearer ").strip()
            if auth_header.lower().startswith("bearer ")
            else None
        )
        identity = identity_from_token(token or bearer)
    except HTTPException:
        await websocket.close(code=4401)
        return

    run = await RunRepositorySQL(app.state.db).get(run_id)
    if run is None:
        await websocket.close(code=4404)
        return
    if (
        settings.auth_mode == "session"
        and run.workspace_id != identity["workspace_id"]
    ):
        await websocket.close(code=4403)
        return

    await websocket.accept()
    events = EventRepository(app.state.db)
    try:
        replayed = await events.list_events(run_id)
        for event in replayed:
            await websocket.send_json(event.to_wire())
        if any(e.type.value in ("done", "error") for e in replayed):
            await websocket.close()
            return
        pubsub = app.state.redis.pubsub()
        await pubsub.subscribe(events_channel(run_id))
        try:
            while True:
                # Bound Redis polls so a closed client / stuck fakeredis cannot
                # pin the handler forever.
                try:
                    message = await asyncio.wait_for(
                        pubsub.get_message(
                            ignore_subscribe_messages=True, timeout=0.5
                        ),
                        timeout=1.5,
                    )
                except asyncio.TimeoutError:
                    message = None
                if message is None:
                    # Soft disconnect probe: aborted sends mean the client left.
                    try:
                        await asyncio.wait_for(websocket.receive(), timeout=0.01)
                    except asyncio.TimeoutError:
                        pass
                    except WebSocketDisconnect:
                        break
                    continue
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode()
                payload = json.loads(data)
                try:
                    await websocket.send_json(payload)
                except (WebSocketDisconnect, RuntimeError):
                    break
                if payload.get("type") in ("done", "error"):
                    break
        finally:
            await pubsub.unsubscribe(events_channel(run_id))
            await pubsub.aclose()
    except WebSocketDisconnect:
        pass
