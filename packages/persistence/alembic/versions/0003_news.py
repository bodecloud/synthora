"""News subscriptions/items and run_metrics tables.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "news_subscriptions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("workspace_id", sa.String(64), nullable=False, index=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("cadence", sa.String(32), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "news_items",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "subscription_id",
            sa.String(32),
            sa.ForeignKey("news_subscriptions.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "run_metrics",
        sa.Column(
            "run_id",
            sa.String(32),
            sa.ForeignKey("research_runs.id"),
            primary_key=True,
        ),
        sa.Column("llm_calls", sa.Integer(), nullable=False),
        sa.Column("prompt_chars", sa.Integer(), nullable=False),
        sa.Column("completion_chars", sa.Integer(), nullable=False),
        sa.Column("search_calls", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("run_metrics")
    op.drop_table("news_items")
    op.drop_table("news_subscriptions")
