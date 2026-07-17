"""Unique constraint on provider_settings (workspace_id, key).

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-17

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_provider_settings_ws_key",
        "provider_settings",
        ["workspace_id", "key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_provider_settings_ws_key",
        "provider_settings",
        type_="unique",
    )
