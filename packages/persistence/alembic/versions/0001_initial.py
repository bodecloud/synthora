"""Initial schema: users, workspaces, sessions, runs, events, artifacts,
citations, knowledge map, discourse, documents, provider settings.

Revision ID: 0001
Revises:
Create Date: 2026-07-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("username", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("owner_id", sa.String(32), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_id", sa.String(32), sa.ForeignKey("workspaces.id"), nullable=False
        ),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "research_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "session_id", sa.String(32), sa.ForeignKey("sessions.id"), nullable=True
        ),
        sa.Column("workspace_id", sa.String(64), nullable=False, index=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("brief", sa.Text(), nullable=True),
        sa.Column("pipeline_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, index=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "run_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey("research_runs.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("node", sa.String(128), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey("research_runs.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "citations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey("research_runs.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("index", sa.Integer(), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "knowledge_nodes",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey("research_runs.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.String(32), nullable=True),
        sa.Column("infos", sa.JSON(), nullable=False),
    )
    op.create_table(
        "knowledge_edges",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey("research_runs.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("source_id", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(32), nullable=False),
        sa.Column("relation", sa.String(128), nullable=False),
    )
    op.create_table(
        "discourse_turns",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey("research_runs.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("speaker", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("utterance", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(32), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("workspace_id", sa.String(64), nullable=False, index=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "provider_settings",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("workspace_id", sa.String(64), nullable=False, index=True),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "provider_settings",
        "documents",
        "discourse_turns",
        "knowledge_edges",
        "knowledge_nodes",
        "citations",
        "artifacts",
        "run_events",
        "research_runs",
        "sessions",
        "workspaces",
        "users",
    ):
        op.drop_table(table)
