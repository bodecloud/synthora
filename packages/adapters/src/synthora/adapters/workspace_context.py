"""Process-local workspace scope for RAG / collection search."""

from __future__ import annotations

from contextvars import ContextVar, Token

_workspace_id: ContextVar[str] = ContextVar("synthora_workspace_id", default="default")


def get_workspace_id() -> str:
    return _workspace_id.get()


def set_workspace_id(workspace_id: str) -> Token:
    return _workspace_id.set(workspace_id or "default")


def reset_workspace_id(token: Token) -> None:
    _workspace_id.reset(token)
