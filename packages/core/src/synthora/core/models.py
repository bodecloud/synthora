"""Domain models shared across the platform, orchestration, and intelligence layers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ArtifactKind(str, Enum):
    REPORT_MARKDOWN = "report_markdown"
    REPORT_HTML = "report_html"
    OUTLINE = "outline"
    KNOWLEDGE_MAP = "knowledge_map"
    EXPORT_PDF = "export_pdf"
    RAW_NOTES = "raw_notes"
    DISCOURSE_LOG = "discourse_log"
    URL_TO_INFO = "url_to_info"
    INTERRUPT_PAYLOAD = "interrupt_payload"


class User(BaseModel):
    id: str = Field(default_factory=new_id)
    username: str
    password_hash: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


class Workspace(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str = "default"
    owner_id: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


class Session(BaseModel):
    id: str = Field(default_factory=new_id)
    workspace_id: str
    title: str = "Untitled research"
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class RunConfig(BaseModel):
    """Runtime configuration for one research run (R-ODR-6)."""

    pipeline_id: str = "deep_research"
    # model roles (R-ODR-5)
    planner_model: str = "openai:gpt-4o-mini"
    researcher_model: str = "openai:gpt-4o-mini"
    compressor_model: str = "openai:gpt-4o-mini"
    writer_model: str = "openai:gpt-4o"
    critic_model: str = "openai:gpt-4o-mini"
    # search
    search_engines: list[str] = Field(default_factory=lambda: ["searxng"])
    search_strategy: str = "source_based"
    # orchestration limits
    allow_clarification: bool = False
    max_concurrent_research_units: int = 5
    max_researcher_iterations: int = 6
    max_react_tool_calls: int = 10
    max_content_length: int = 50_000
    # intelligence knobs (STORM defaults)
    num_perspectives: int = 3
    max_discourse_turns: int = 12
    knowledge_node_capacity: int = 10
    moderator_alpha: float = 0.5
    # autonomous loop bound
    max_autonomous_cycles: int = 3
    extra: dict[str, Any] = Field(default_factory=dict)


class ResearchRun(BaseModel):
    id: str = Field(default_factory=new_id)
    session_id: Optional[str] = None
    workspace_id: str = "default"
    question: str
    brief: Optional[str] = None
    pipeline_id: str = "deep_research"
    status: RunStatus = RunStatus.QUEUED
    config: RunConfig = Field(default_factory=RunConfig)
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class SearchResult(BaseModel):
    """A single retrieved document snippet from any search engine."""

    url: str
    title: str = ""
    snippet: str = ""
    content: str = ""
    engine: str = ""
    score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class Citation(BaseModel):
    id: str = Field(default_factory=new_id)
    run_id: Optional[str] = None
    url: str
    title: str = ""
    snippet: str = ""
    confidence: float = 1.0
    index: Optional[int] = None  # [n] marker in the report
    verified: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class Perspective(BaseModel):
    """An expert persona used for perspective-guided research (R-STORM-1)."""

    id: str = Field(default_factory=new_id)
    name: str
    description: str = ""
    focus: str = ""


class DiscourseTurn(BaseModel):
    """One utterance in a Co-STORM style collaborative discourse (R-STORM-4)."""

    id: str = Field(default_factory=new_id)
    run_id: Optional[str] = None
    speaker: str  # perspective name, "moderator", or "user"
    role: str = "expert"  # expert | moderator | user
    utterance: str
    intent: str = "answer"  # answer | question | steer
    citations: list[Citation] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class KnowledgeNode(BaseModel):
    """A concept in the hierarchical knowledge map (R-STORM-3)."""

    id: str = Field(default_factory=new_id)
    run_id: Optional[str] = None
    name: str
    summary: str = ""
    parent_id: Optional[str] = None
    infos: list[Citation] = Field(default_factory=list)


class KnowledgeEdge(BaseModel):
    id: str = Field(default_factory=new_id)
    run_id: Optional[str] = None
    source_id: str
    target_id: str
    relation: str = "related_to"


class OutlineNode(BaseModel):
    """A section of the outline-first report structure (R-STORM-5)."""

    title: str
    children: list["OutlineNode"] = Field(default_factory=list)
    knowledge_node_ids: list[str] = Field(default_factory=list)


class Artifact(BaseModel):
    id: str = Field(default_factory=new_id)
    run_id: str
    kind: ArtifactKind
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class Document(BaseModel):
    """Workspace document in the local library (RAG source)."""

    id: str = Field(default_factory=new_id)
    workspace_id: str = "default"
    title: str = ""
    url: Optional[str] = None
    path: Optional[str] = None
    content: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class DocumentChunk(BaseModel):
    """Embedded text chunk belonging to a library document."""

    id: str = Field(default_factory=new_id)
    document_id: str
    workspace_id: str = "default"
    chunk_index: int = 0
    text: str = ""
    embedding: list[float] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class ProviderSetting(BaseModel):
    """Persisted provider/config knobs keyed per workspace."""

    id: str = Field(default_factory=new_id)
    workspace_id: str = "default"
    key: str
    value: dict[str, Any] = Field(default_factory=dict)


class NewsSubscription(BaseModel):
    """News query subscription with cadence-based polling."""

    id: str = Field(default_factory=new_id)
    workspace_id: str = "default"
    query: str
    cadence: str = "daily"  # hourly | daily | weekly
    last_run_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)


class NewsItem(BaseModel):
    id: str = Field(default_factory=new_id)
    subscription_id: str
    title: str = ""
    url: str = ""
    summary: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class RunMetrics(BaseModel):
    """Lightweight cost/usage counters for one research run."""

    run_id: str
    llm_calls: int = 0
    prompt_chars: int = 0
    completion_chars: int = 0
    search_calls: int = 0
    created_at: datetime = Field(default_factory=utcnow)


OutlineNode.model_rebuild()
