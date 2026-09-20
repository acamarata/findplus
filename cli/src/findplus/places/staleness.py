"""Is a device's last fix recent enough to make a claim about where it is?

Purpose    : One definition of the staleness cutoff the Places surface applies,
             split out of repo.py so both stay under the 300-line cap (PRI
             rule 7). geofence.advance() only moves a place_state when a new
             fix arrives, so without this a tracker that entered Home and then
             went silent reads "Home since 3 d" for ever -- the reading
             honesty.md's presence_stale sentence forbids.
Inputs     : An open Session; an optional threshold and clock (tests pass both).
Outputs    : The cutoff, the per-device newest-fix map, and the test itself.
Constraints: Pure reads. The default threshold is
             Settings.presence_window_minutes, the same one group presence uses.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from findplus.db.models import LocationObservation


def _stale_before(stale_after_minutes: int | None, now: datetime | None) -> datetime | None:
    """The cutoff a device's newest fix must beat to count as reporting."""
    if stale_after_minutes is None:
        from findplus.config import get_settings

        stale_after_minutes = get_settings().presence_window_minutes
    return (now or datetime.now(UTC)) - timedelta(minutes=stale_after_minutes)


def _last_fix_by_device(session: Session) -> dict[str, datetime]:
    """device_id -> its newest observed_at. One query, not one per row."""
    rows = session.execute(
        select(
            LocationObservation.device_id,
            func.max(LocationObservation.observed_at),
        ).group_by(LocationObservation.device_id)
    ).all()
    return {device_id: observed_at for device_id, observed_at in rows if observed_at}


def _is_stale(last_fix: datetime | None, cutoff: datetime) -> bool:
    if last_fix is None:
        return True
    if last_fix.tzinfo is None:
        last_fix = last_fix.replace(tzinfo=UTC)
    return last_fix < cutoff
