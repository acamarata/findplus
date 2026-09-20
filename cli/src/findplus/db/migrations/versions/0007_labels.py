"""device labels/icons/colours and group icons

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-20
"""

from __future__ import annotations

import hashlib

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str = "0006"
branch_labels = None
depends_on = None

# The first eight entries are the retired web/app/state.js TRACK_COLORS in their
# exact order, so a device the dashboard had already coloured keeps that colour;
# four more follow to widen the wheel. This list is deliberately duplicated in
# findplus/labels.py: an Alembic revision has to stay runnable forever, long
# after labels.py has moved on. cli/tests/test_labels.py asserts the two copies
# and the two hash formulas agree, so the duplication can never drift silently.
DEVICE_PALETTE = [
    "#4f8cf7",
    "#e7663f",
    "#37c67a",
    "#c77ae6",
    "#e7b53f",
    "#3fc9d6",
    "#e64f7a",
    "#8fb43f",
    "#f2994a",
    "#9b6bd6",
    "#4fd6a8",
    "#d65f5f",
]


def _palette_color(device_id: str) -> str:
    digest = hashlib.sha1(device_id.encode("utf-8")).hexdigest()
    return DEVICE_PALETTE[int(digest, 16) % 12]


def upgrade() -> None:
    with op.batch_alter_table("devices") as batch_op:
        batch_op.add_column(sa.Column("label", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("icon", sa.String(32), nullable=False, server_default="letter")
        )
        batch_op.add_column(
            sa.Column("color", sa.String(16), nullable=False, server_default="#888888")
        )
    bind = op.get_bind()
    # A device that existed before this revision must land on the same colour it
    # would get if it were discovered tomorrow, which is why the backfill runs
    # the identical hash rather than handing out the palette in row order.
    for device_id in bind.execute(sa.text("SELECT device_id FROM devices")).scalars():
        bind.execute(
            sa.text("UPDATE devices SET color = :c WHERE device_id = :id"),
            {"c": _palette_color(device_id), "id": device_id},
        )
    with op.batch_alter_table("groups") as batch_op:
        batch_op.add_column(
            sa.Column("icon", sa.String(32), nullable=False, server_default="lucide:users")
        )


def downgrade() -> None:
    with op.batch_alter_table("groups") as batch_op:
        batch_op.drop_column("icon")
    with op.batch_alter_table("devices") as batch_op:
        batch_op.drop_column("color")
        batch_op.drop_column("icon")
        batch_op.drop_column("label")
