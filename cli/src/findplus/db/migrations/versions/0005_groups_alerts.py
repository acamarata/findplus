"""groups, device_group, group_place_events, alert_rules, alert_deliveries tables

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str = "0004"
branch_labels = None
depends_on = None


def _create_groups_table() -> None:
    op.create_table(
        "groups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("color", sa.String(16), nullable=False, server_default="#27ae60"),
        sa.Column("quorum", sa.String(16), nullable=False, server_default="majority"),
        sa.Column("cluster_radius_meters", sa.Integer(), nullable=False, server_default="150"),
        sa.Column("stale_after_minutes", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "cluster_radius_meters BETWEEN 25 AND 2000", name="ck_groups_cluster_radius"
        ),
        sa.CheckConstraint("stale_after_minutes BETWEEN 10 AND 1440", name="ck_groups_stale_after"),
    )


def _create_device_group_table() -> None:
    op.create_table(
        "device_group",
        sa.Column("device_id", sa.String(128), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id", "group_id"),
    )


def _create_group_place_events_table() -> None:
    op.create_table(
        "group_place_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("place_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(5), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("member_event_ids", sa.Text(), nullable=False),
        sa.Column("members_crossed", sa.Integer(), nullable=False),
        sa.Column("members_considered", sa.Integer(), nullable=False),
        sa.Column("members_stale", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.String(6), nullable=True),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("event_type IN ('ENTER','EXIT')", name="ck_gpe_type"),
        sa.CheckConstraint("confidence IN ('high','medium','low')", name="ck_gpe_confidence"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["place_id"], ["places.id"], ondelete="CASCADE"),
    )


def _create_alert_rules_table() -> None:
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("place_id", sa.Integer(), nullable=True),
        sa.Column("group_id", sa.Integer(), nullable=True),
        sa.Column("device_id", sa.String(128), nullable=True),
        sa.Column("on_enter", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("on_exit", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("also_notify_members", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("channel IN ('telegram','webhook')", name="ck_alert_rules_channel"),
        sa.CheckConstraint("cooldown_minutes BETWEEN 0 AND 1440", name="ck_alert_rules_cooldown"),
        sa.CheckConstraint(
            "(group_id IS NULL) <> (device_id IS NULL)", name="ck_alert_rules_xor_target"
        ),
        sa.ForeignKeyConstraint(["place_id"], ["places.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"], ondelete="CASCADE"),
    )


def _create_alert_deliveries_table() -> None:
    op.create_table(
        "alert_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("event_kind", sa.String(6), nullable=True),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(8), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint("event_kind IN ('device','group')", name="ck_alert_deliveries_kind"),
        sa.CheckConstraint(
            "status IN ('sent','failed','skipped')", name="ck_alert_deliveries_status"
        ),
        sa.ForeignKeyConstraint(["rule_id"], ["alert_rules.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("rule_id", "event_kind", "event_id", name="uq_alert_deliveries_dedup"),
    )


def _create_group_place_events_index() -> None:
    op.create_index(
        "ix_gpe_group_place_observed",
        "group_place_events",
        ["group_id", "place_id", "observed_at"],
    )


def upgrade() -> None:
    """Same table/index order as before the split (E13 loop2 A3, cap only)."""
    _create_groups_table()
    _create_device_group_table()
    _create_group_place_events_table()
    _create_alert_rules_table()
    _create_alert_deliveries_table()
    _create_group_place_events_index()


def downgrade() -> None:
    op.drop_index("ix_gpe_group_place_observed", table_name="group_place_events")
    op.drop_table("alert_deliveries")
    op.drop_table("alert_rules")
    op.drop_table("group_place_events")
    op.drop_table("device_group")
    op.drop_table("groups")
