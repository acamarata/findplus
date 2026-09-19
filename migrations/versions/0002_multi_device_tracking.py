"""multi-device tracking

Replaces the single `is_selected` flag with `is_tracked`, so any number of
Find Hub devices can be polled concurrently. Existing selections are preserved.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("devices") as batch:
        batch.add_column(
            sa.Column("is_tracked", sa.Boolean(), nullable=False, server_default=sa.text("0"))
        )
    # Anything previously selected stays tracked.
    op.execute("UPDATE devices SET is_tracked = is_selected")
    with op.batch_alter_table("devices") as batch:
        batch.drop_column("is_selected")

    op.create_index("ix_devices_tracked", "devices", ["is_tracked"])


def downgrade() -> None:
    op.drop_index("ix_devices_tracked", table_name="devices")
    with op.batch_alter_table("devices") as batch:
        batch.add_column(
            sa.Column("is_selected", sa.Boolean(), nullable=False, server_default=sa.text("0"))
        )
    op.execute("UPDATE devices SET is_selected = is_tracked")
    with op.batch_alter_table("devices") as batch:
        batch.drop_column("is_tracked")
