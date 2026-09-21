"""places, place_events, place_states tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str = "0003"
branch_labels = None
depends_on = None


def _create_places_table() -> None:
    op.create_table(
        "places",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("latitude_e7", sa.Integer(), nullable=False),
        sa.Column("longitude_e7", sa.Integer(), nullable=False),
        sa.Column("radius_meters", sa.Integer(), nullable=False),
        sa.Column("color", sa.String(16), nullable=False, server_default="#2f80ed"),
        sa.Column("enter_confirmations", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("exit_confirmations", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "radius_meters >= 20 AND radius_meters <= 5000", name="ck_places_radius"
        ),
        sa.CheckConstraint("enter_confirmations BETWEEN 1 AND 5", name="ck_places_enter_conf"),
        sa.CheckConstraint("exit_confirmations BETWEEN 1 AND 5", name="ck_places_exit_conf"),
    )


def _create_place_events_table() -> None:
    op.create_table(
        "place_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("place_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(128), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(5), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("observation_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.String(6), nullable=False),
        sa.Column("distance_meters", sa.Float(), nullable=False),
        sa.Column("accuracy_meters", sa.Float(), nullable=True),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("event_type IN ('ENTER','EXIT')", name="ck_place_events_type"),
        sa.CheckConstraint("confidence IN ('high','medium','low')", name="ck_place_events_conf"),
        sa.ForeignKeyConstraint(["place_id"], ["places.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"]),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["location_observations.id"], ondelete="CASCADE"
        ),
    )


def _create_place_events_indexes() -> None:
    op.create_index(
        "ix_place_events_place_device_observed",
        "place_events",
        ["place_id", "device_id", "observed_at"],
    )
    op.create_index("ix_place_events_observed", "place_events", ["observed_at"])


def _create_place_states_table() -> None:
    op.create_table(
        "place_states",
        sa.Column("place_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(128), nullable=False),
        sa.Column("state", sa.String(8), nullable=False, server_default="unknown"),
        sa.Column("since_observed_at", sa.DateTime(), nullable=True),
        sa.Column("streak", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("streak_side", sa.String(8), nullable=True),
        sa.Column("last_observation_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("state IN ('inside','outside','unknown')", name="ck_place_states_state"),
        sa.ForeignKeyConstraint(["place_id"], ["places.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"]),
        sa.PrimaryKeyConstraint("place_id", "device_id"),
    )


def upgrade() -> None:
    """Same table/index order as before the split (E13 loop2 A3, cap only)."""
    _create_places_table()
    _create_place_events_table()
    _create_place_states_table()
    _create_place_events_indexes()


def downgrade() -> None:
    op.drop_index("ix_place_events_observed", table_name="place_events")
    op.drop_index("ix_place_events_place_device_observed", table_name="place_events")
    op.drop_table("place_states")
    op.drop_table("place_events")
    op.drop_table("places")
