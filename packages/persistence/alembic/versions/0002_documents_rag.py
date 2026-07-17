"""Document chunks table for local library RAG.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(32),
            sa.ForeignKey("documents.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("workspace_id", sa.String(64), nullable=False, index=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("document_chunks")
