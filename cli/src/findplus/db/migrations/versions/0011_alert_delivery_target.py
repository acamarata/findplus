"""alert_deliveries: per-target column for multi-target channels (Telegram)

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-25

The owner asked for a Telegram rule to notify several chats (a person, a
group, or several people, comma-delimited). dispatch.py now sends one row
per (rule, event, channel, target) instead of one per (rule, event, channel)
so a failing target retries on its own without resending to a target that
already succeeded (alerts/retry.py already retries one row at a time; this
just gives it more rows to work with).

1. `alert_deliveries`: add `target TEXT NOT NULL DEFAULT ''` -- empty string,
   not NULL, for every channel that has no per-target concept (webhook,
   whatsapp, native): SQLite's UNIQUE treats every NULL as distinct from
   every other NULL, which would silently defeat `uq_alert_deliveries_dedup`
   for those channels' race-safety net (two concurrent pollers both winning
   the "not already delivered" check). A non-NULL default keeps the
   constraint doing real work for the channels that never see more than one
   row per event anyway. Existing rows backfill to `''` -- every pre-0011
   delivery was already a single-target send.
2. Widen `uq_alert_deliveries_dedup` from `(rule_id, event_kind, event_id,
   channel)` to `(rule_id, event_kind, event_id, channel, target)`.

downgrade() drops the column and narrows the constraint back. A downgrade
after a rule has actually fanned out to more than one Telegram target would
leave more than one row per (rule, event, channel) with no `target` to tell
them apart -- acceptable data loss on a manual downgrade, same as 0008's own
downgrade note about channel/status collapsing.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str = "0010"
branch_labels = None
depends_on = None

_OLD_UNIQUE_COLS = ("rule_id", "event_kind", "event_id", "channel")
_NEW_UNIQUE_COLS = ("rule_id", "event_kind", "event_id", "channel", "target")


def upgrade() -> None:
    with op.batch_alter_table("alert_deliveries") as batch:
        batch.add_column(
            sa.Column("target", sa.String(length=64), nullable=False, server_default="")
        )
        batch.drop_constraint("uq_alert_deliveries_dedup", type_="unique")
        batch.create_unique_constraint("uq_alert_deliveries_dedup", list(_NEW_UNIQUE_COLS))


def downgrade() -> None:
    with op.batch_alter_table("alert_deliveries") as batch:
        batch.drop_constraint("uq_alert_deliveries_dedup", type_="unique")
        batch.create_unique_constraint("uq_alert_deliveries_dedup", list(_OLD_UNIQUE_COLS))
        batch.drop_column("target")
