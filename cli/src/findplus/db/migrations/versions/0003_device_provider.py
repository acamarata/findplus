"""devices.provider column and ix_devices_provider index

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("devices") as batch_op:
        batch_op.add_column(
            sa.Column(
                "provider",
                sa.String(32),
                nullable=False,
                server_default="google-find-hub",
            )
        )
        batch_op.create_index("ix_devices_provider", ["provider"])


def downgrade() -> None:
    with op.batch_alter_table("devices") as batch_op:
        batch_op.drop_index("ix_devices_provider")
        batch_op.drop_column("provider")
