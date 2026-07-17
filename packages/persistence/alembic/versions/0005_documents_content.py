"""Add documents.content column (was previously stuffed into meta).

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
    )
    # Backfill from meta->>'content' when present (Postgres).
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                """
                UPDATE documents
                SET content = COALESCE(meta->>'content', '')
                WHERE content = '' OR content IS NULL
                """
            )
        )


def downgrade() -> None:
    op.drop_column("documents", "content")
