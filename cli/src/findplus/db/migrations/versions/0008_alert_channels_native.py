"""alert_rules.channel -> channels; alert_deliveries channel + delivered_at

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-20

Two things about this revision are load-bearing and neither is incidental.

1. Step order (specs/notifications.md § 0): alert_deliveries.channel is backfilled
   from alert_rules.channel while that column still exists, and alert_rules.channel
   is only dropped afterwards. Reversing the blocks drops the backfill source
   before it is read.

2. alert_deliveries.rule_id is ON DELETE CASCADE. Alembic's SQLite batch mode
   rebuilds a table by copying it and DROPping the original, and that DROP fires
   the cascade, so altering alert_rules with foreign keys enforced silently wipes
   every delivery row. findplus.db.session turns PRAGMA foreign_keys ON for every
   connection, including the one migrations run on, so this revision turns it off
   around the alert_rules rebuilds AND stashes the delivery rows first. The pragma
   alone would be enough today (Alembic's SQLite impl runs DDL outside a
   transaction, where the pragma still takes effect), but it is silently a no-op
   inside one, and a silent no-op here costs the user their delivery history.

3. downgrade() cannot re-create alert_deliveries' pre-0008 shape by just putting
   the stashed rows back (CR-C-E8 F3). Two things a real 1.1 database can hold
   don't fit that shape: a `queued` or `delivered` status (native's own states,
   outside 0007's `sent`/`failed`/`skipped` CHECK), and more than one row for the
   same (rule_id, event_kind, event_id) under different channels (0007's UNIQUE
   has no `channel` column, so multi-channel rules collide on it). Before the
   final batch rebuild narrows both constraints back down, this revision remaps
   `delivered -> sent` (the row did get through, which is what `sent` meant in
   1.0) and `queued -> skipped` (no confirmation ever arrived, the same state a
   1.0 delivery attempt that never fired would have left), then keeps only the
   earliest row (MIN(id), same dedup shape as 0006's R-P2-15 fix) per
   (rule_id, event_kind, event_id) so the narrowed UNIQUE has nothing left to
   collide on. A round-trip (upgrade head -> downgrade 0006 -> upgrade head) on
   a database seeded with queued/delivered and multi-channel rows is the
   regression test for this.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str = "0007"
branch_labels = None
depends_on = None

_STASH = "_alert_deliveries_0008_stash"
_STATUS_NEW = "status IN ('sent','failed','skipped','queued','delivered')"
_STATUS_OLD = "status IN ('sent','failed','skipped')"


def _stash_deliveries() -> None:
    """Copy alert_deliveries aside before a cascade-firing alert_rules rebuild."""
    op.execute("PRAGMA foreign_keys=OFF")
    op.execute(f"DROP TABLE IF EXISTS {_STASH}")
    op.execute(f"CREATE TABLE {_STASH} AS SELECT * FROM alert_deliveries")


def _restore_deliveries() -> None:
    """Put the stashed rows back, whether or not the cascade actually fired."""
    op.execute("DELETE FROM alert_deliveries")
    op.execute(f"INSERT INTO alert_deliveries SELECT * FROM {_STASH}")
    op.execute(f"DROP TABLE {_STASH}")
    op.execute("PRAGMA foreign_keys=ON")


def upgrade() -> None:
    # alert_deliveries first: nothing references it, so rebuilding it is safe, and
    # its channel column has to exist before the backfill can write to it.
    with op.batch_alter_table("alert_deliveries") as batch:
        batch.add_column(sa.Column("channel", sa.String(16), nullable=True))
        batch.add_column(sa.Column("delivered_at", sa.DateTime(), nullable=True))
    op.execute(
        "UPDATE alert_deliveries SET channel = ("
        "SELECT channel FROM alert_rules WHERE alert_rules.id = alert_deliveries.rule_id)"
    )
    op.execute("UPDATE alert_deliveries SET channel = 'telegram' WHERE channel IS NULL")
    with op.batch_alter_table("alert_deliveries") as batch:
        batch.alter_column("channel", existing_type=sa.String(16), nullable=False)
        batch.drop_constraint("ck_alert_deliveries_status", type_="check")
        batch.create_check_constraint("ck_alert_deliveries_status", _STATUS_NEW)
        batch.drop_constraint("uq_alert_deliveries_dedup", type_="unique")
        batch.create_unique_constraint(
            "uq_alert_deliveries_dedup", ["rule_id", "event_kind", "event_id", "channel"]
        )

    _stash_deliveries()
    with op.batch_alter_table("alert_rules") as batch:
        batch.drop_constraint("ck_alert_rules_channel", type_="check")
        batch.add_column(
            sa.Column("channels", sa.Text(), nullable=False, server_default="telegram")
        )
    op.execute("UPDATE alert_rules SET channels = channel")
    with op.batch_alter_table("alert_rules") as batch:
        batch.drop_column("channel")
    _restore_deliveries()


def downgrade() -> None:
    _stash_deliveries()
    with op.batch_alter_table("alert_rules") as batch:
        batch.add_column(sa.Column("channel", sa.String(16), nullable=True))
    op.execute(
        "UPDATE alert_rules SET channel = substr(channels, 1, instr(channels || ',', ',') - 1)"
    )
    # 0007's CHECK only knows telegram and webhook. A rule whose first channel is
    # native or whatsapp would fail it, making the downgrade impossible on any
    # database that used 1.1's new channels, so those rules fall back to telegram.
    op.execute("UPDATE alert_rules SET channel = 'telegram' WHERE channel NOT IN ('webhook')")
    with op.batch_alter_table("alert_rules") as batch:
        batch.alter_column("channel", existing_type=sa.String(16), nullable=False)
        batch.create_check_constraint("ck_alert_rules_channel", "channel IN ('telegram','webhook')")
        batch.drop_column("channels")
    # 0007's status CHECK and dedup UNIQUE are both narrower than what a real
    # 1.1 database can hold (see module docstring point 3) -- reshape the data
    # to fit before it is restored, so it does not violate the old constraints
    # if the cascade rebuild already re-applied them.
    op.execute(f"UPDATE {_STASH} SET status = 'sent' WHERE status = 'delivered'")
    op.execute(f"UPDATE {_STASH} SET status = 'skipped' WHERE status = 'queued'")
    op.execute(
        f"DELETE FROM {_STASH} WHERE id NOT IN ("
        f"  SELECT MIN(id) FROM {_STASH} GROUP BY rule_id, event_kind, event_id"
        ")"
    )
    _restore_deliveries()
    with op.batch_alter_table("alert_deliveries") as batch:
        batch.drop_constraint("uq_alert_deliveries_dedup", type_="unique")
        batch.create_unique_constraint(
            "uq_alert_deliveries_dedup", ["rule_id", "event_kind", "event_id"]
        )
        batch.drop_constraint("ck_alert_deliveries_status", type_="check")
        batch.create_check_constraint("ck_alert_deliveries_status", _STATUS_OLD)
        batch.drop_column("channel")
        batch.drop_column("delivered_at")
