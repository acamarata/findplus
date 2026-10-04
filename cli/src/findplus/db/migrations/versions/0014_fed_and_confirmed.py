"""Two derived-state markers: observation_quality.fed_at, person_place_states.confirmed_at

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-04

Plain nullable column adds (no table rebuild, nothing cascades from either table).

1. `observation_quality.fed_at`: when the observation was handed to the geofence
   hooks. A fix that was fed clean, later flagged and cleared again is not fed a
   second time. Backfilled with `computed_at` for every row that is not suspect
   now (those were fed when they were scored).
2. `person_place_states.confirmed_at`: the last evaluation whose evidence agreed
   with the stored side. A person state nothing has confirmed for 12 hours
   becomes unknown instead of holding for ever (people/expiry.py). Backfilled
   with `since_observed_at`, the last evaluation, for every known state.

downgrade() drops both columns; nothing else reads them.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("observation_quality", sa.Column("fed_at", sa.DateTime(), nullable=True))
    op.add_column("person_place_states", sa.Column("confirmed_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE observation_quality SET fed_at = computed_at WHERE suspect = 0")
    op.execute(
        "UPDATE person_place_states SET confirmed_at = since_observed_at WHERE state != 'unknown'"
    )


def downgrade() -> None:
    with op.batch_alter_table("person_place_states") as batch:
        batch.drop_column("confirmed_at")
    with op.batch_alter_table("observation_quality") as batch:
        batch.drop_column("fed_at")
