"""Progress events emitted by pipelines and streamed over WebSocket (R-LDR-3)."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class RunEventType(str, Enum):
    STATUS = "status"
    NODE_STARTED = "node_started"
    NODE_FINISHED = "node_finished"
    SEARCH_ISSUED = "search_issued"
    SOURCE_FOUND = "source_found"
    PERSPECTIVE_CREATED = "perspective_created"
    DISCOURSE_TURN = "discourse_turn"
    KNOWLEDGE_UPDATED = "knowledge_updated"
    OUTLINE_READY = "outline_ready"
    SECTION_WRITTEN = "section_written"
    CRITIQUE = "critique"
    INTERRUPT = "interrupt"
    ERROR = "error"
    DONE = "done"


class ProgressEvent(BaseModel):
    run_id: str
    type: RunEventType
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    node: Optional[str] = None
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_wire(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        return data
