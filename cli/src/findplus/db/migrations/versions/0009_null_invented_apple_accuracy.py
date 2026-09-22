"""Null out invented Apple Find My accuracy values (CF-P2-6 / R-P2-27 item 2)

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-22

Data-only migration, no schema change.

A revision of `apple_findmy/provider.py` shipped in v1.0.0 (commit `84887b6`,
tagged 2026-09-19) mapped each FindMy.py confidence label to a fixed,
invented metres figure -- excellent=10.0, good=30.0, medium=65.0, poor=150.0
-- and stored it in `location_observations.accuracy_meters` as if it were a
measured reading. That invention was caught in E1 honesty round 2 (F9,
deferred as CF-P2-6) and removed in commit `d2403b2` (2026-09-20 21:27
-0400), which always writes `accuracy_meters=None` for Apple observations.
Any local database upgraded straight from v1.0.0 can still hold rows
ingested during that ~26-hour window with one of the four invented values.

This only touches rows this heuristic could actually have written: source
IS 'apple-find-my' AND accuracy_meters is exactly one of the four constants
(floating-point equality is safe here because the old code wrote these
literals verbatim, never a computed or rounded value). A row a user entered,
or that some other future Apple accuracy source measured, that happens to
equal one of these four numbers is not distinguishable from this heuristic's
output by value alone -- accepted, since this is the same value-based
approach `0006`'s and `0008`'s data cleanups use, and the alternative (a
`is_estimated` flag never added to 1.0/1.1's `location_observations` schema)
is not available to retrofit here.

Closeout review G3 raised exactly that ambiguity -- a genuine Apple reading of
10.0/30.0/65.0/150.0 metres nulled by mistake -- and it was ruled no change:
v1.0.0 shipped with no measured Apple Find My accuracy source at all (Find
My.py surfaces only the confidence label this heuristic mapped from, never a
metres figure of its own), so every non-null `accuracy_meters` an Apple
observation carried before `d2403b2` was this heuristic's output, never a
real measurement. There is no genuine value in that window for the WHERE
clause to lose.

downgrade() cannot restore the original invented figures -- they are gone,
which is the point of this migration -- so it is a documented no-op.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str = "0008"
branch_labels = None
depends_on = None

#: The exact constants the removed `CONFIDENCE_TO_ACCURACY` dict wrote,
#: keyed by findmy confidence label, for excellent/good/medium/poor.
_INVENTED_VALUES = (10.0, 30.0, 65.0, 150.0)


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE location_observations SET accuracy_meters = NULL "
            "WHERE source = 'apple-find-my' AND accuracy_meters IN "
            "(:v0, :v1, :v2, :v3)"
        ).bindparams(
            v0=_INVENTED_VALUES[0],
            v1=_INVENTED_VALUES[1],
            v2=_INVENTED_VALUES[2],
            v3=_INVENTED_VALUES[3],
        )
    )


def downgrade() -> None:
    # No-op by design: the invented figures this revision removes are not
    # recoverable, and re-inventing them on downgrade would reintroduce the
    # exact honesty defect this migration exists to fix.
    pass
