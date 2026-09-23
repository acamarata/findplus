"""alert_deliveries retry: attempts, next_attempt_at, 'retrying' status

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-22

The owner asked for retries on transient delivery failures (P1 seed "alert
delivery retry", ruled out of 1.0 by F2, back in scope for 1.1). Two columns
and a widened status CHECK, no table rebuild risk like 0008's (this touches
only alert_deliveries, which nothing else cascades from):

1. `attempts INTEGER NOT NULL DEFAULT 1` -- send attempts made so far. Every
   pre-0010 row already represents exactly one attempt (dispatch.py's
   `_deliver_one` has only ever made one), so 1 is the correct backfill, not
   a placeholder.
2. `next_attempt_at` (nullable) -- when the next retry is due for a
   `status='retrying'` row; NULL for every other status.
3. `ck_alert_deliveries_status` widens to add `'retrying'`.

downgrade() maps `retrying` -> `failed` (the row never reached a successful
send, which is what `failed` already means for every pre-1.1 reader) before
narrowing the CHECK back and dropping both columns.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str = "0009"
branch_labels = None
depends_on = None

_STATUS_NEW = "status IN ('sent','failed','skipped','queued','delivered','retrying')"
_STATUS_OLD = "status IN ('sent','failed','skipped','queued','delivered')"


def upgrade() -> None:
    with op.batch_alter_table("alert_deliveries") as batch:
        batch.add_column(sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("next_attempt_at", sa.DateTime(), nullable=True))
        batch.drop_constraint("ck_alert_deliveries_status", type_="check")
        batch.create_check_constraint("ck_alert_deliveries_status", _STATUS_NEW)


def downgrade() -> None:
    op.execute("UPDATE alert_deliveries SET status = 'failed' WHERE status = 'retrying'")
    with op.batch_alter_table("alert_deliveries") as batch:
        batch.drop_constraint("ck_alert_deliveries_status", type_="check")
        batch.create_check_constraint("ck_alert_deliveries_status", _STATUS_OLD)
        batch.drop_column("attempts")
        batch.drop_column("next_attempt_at")
