"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _create_devices_table() -> None:
    op.create_table(
        "devices",
        sa.Column("device_id", sa.String(length=128), primary_key=True),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("is_selected", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
    )


def _create_location_observations_table() -> None:
    op.create_table(
        "location_observations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "device_id", sa.String(length=128), sa.ForeignKey("devices.device_id"), nullable=False
        ),
        sa.Column("device_name", sa.String(length=256), nullable=False),
        sa.Column("latitude_e7", sa.Integer(), nullable=False),
        sa.Column("longitude_e7", sa.Integer(), nullable=False),
        sa.Column("altitude_meters", sa.Float(), nullable=True),
        sa.Column("accuracy_meters", sa.Float(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("first_fetched_at", sa.DateTime(), nullable=False),
        sa.Column("last_fetched_at", sa.DateTime(), nullable=False),
        sa.Column("times_returned", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("is_own_report", sa.Boolean(), nullable=True),
        sa.Column("semantic_name", sa.String(length=256), nullable=True),
        sa.Column("battery_level", sa.Integer(), nullable=True),
        sa.Column("raw_metadata", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "device_id",
            "observed_at",
            "latitude_e7",
            "longitude_e7",
            name="uq_observation_identity",
        ),
    )
    op.create_index("ix_obs_device_observed", "location_observations", ["device_id", "observed_at"])
    op.create_index("ix_obs_observed", "location_observations", ["observed_at"])
    op.create_index(
        "ix_obs_device_fetched", "location_observations", ["device_id", "first_fetched_at"]
    )


def _create_poll_runs_table() -> None:
    op.create_table(
        "poll_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("device_id", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "observations_returned", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("observations_new", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_type", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_pollrun_started", "poll_runs", ["started_at"])


def _create_settings_table() -> None:
    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def upgrade() -> None:
    """Same table/index order as before the split (E13 loop2 A3, cap only)."""
    _create_devices_table()
    _create_location_observations_table()
    _create_poll_runs_table()
    _create_settings_table()


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_index("ix_pollrun_started", table_name="poll_runs")
    op.drop_table("poll_runs")
    op.drop_index("ix_obs_device_fetched", table_name="location_observations")
    op.drop_index("ix_obs_observed", table_name="location_observations")
    op.drop_index("ix_obs_device_observed", table_name="location_observations")
    op.drop_table("location_observations")
    op.drop_table("devices")
