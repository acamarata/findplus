"""alert_rules: optional per-rule Telegram target subset.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-26

The owner asked for a Telegram alert to go to a group, a person, or two
people -- today every Telegram rule fans out to the account's whole saved
target list (gap-audit 2026-09-26, P13/WP10). This adds
`alert_rules.telegram_targets`, a nullable comma-separated subset of the
saved Telegram chat ids:

- NULL (every existing row backfills to this) means "every saved target",
  the exact pre-migration behaviour -- an upgraded install's rules keep
  fanning out to every saved chat with no action needed.
- A stored value, including the empty string, is an explicit subset: `""`
  means the owner picked no chat at all (dispatch.py skips Telegram for
  that rule rather than surprising them with "all" again), and "111,-100222"
  means exactly those two chats.

No CHECK constraint and no FK to a targets table: targets live in
alerts.json (alerts/store.py), not a DB table, so validation is API-layer
only (alerts/rule_telegram_targets.py), the same posture migration 0011's
own docstring describes for `channels`.

downgrade() drops the column. A downgrade after a rule was ever narrowed to
a subset loses which chats it was limited to -- the rule reverts to sending
to every saved target on its next alert, acceptable data loss on a manual
downgrade (same posture as 0008's channel/status collapse note).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("alert_rules") as batch:
        batch.add_column(sa.Column("telegram_targets", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("alert_rules") as batch:
        batch.drop_column("telegram_targets")
