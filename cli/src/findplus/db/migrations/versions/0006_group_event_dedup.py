"""group_place_events dedup constraint (CF-8)

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-20
"""

from __future__ import annotations

from alembic import op

revision: str = "0006"
down_revision: str = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ruling R-P2-15: the key carries observed_at. Without it the constraint is
    # global, so a group could log exactly one ENTER and one EXIT per place for
    # all time and every genuine later crossing would be rolled back. The
    # +/-window dedup stays in groups/events.py:_existing_group_event, which no
    # table constraint can express; this one closes the exact-duplicate race.
    with op.batch_alter_table("group_place_events") as batch_op:
        batch_op.create_unique_constraint(
            "uq_gpe_dedup", ["group_id", "place_id", "event_type", "observed_at"]
        )


def downgrade() -> None:
    with op.batch_alter_table("group_place_events") as batch_op:
        batch_op.drop_constraint("uq_gpe_dedup", type_="unique")
