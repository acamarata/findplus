"""Per-member timeline assembly for a group, split out of repo.py to stay under 300 lines.

Purpose : Build the group-timeline shape routes_history.py serves, one point list per
          member device, never merged (PROMPT.md §2 invariant 5).
Inputs  : An open Session (caller-owned transaction), a group id, and a UTC window.
Outputs : `list[dict]` — one `{device_id, name, points}` entry per member device.
Constraints: Never commits. Caller (routes_history.py) owns the group-not-found 404.
Reuse: re-exported from findplus.groups.repo so existing imports are unchanged
       (same pattern as findplus.poller re-exporting findplus.poller_outcomes).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from findplus.db.models import Device, DeviceGroup, LocationObservation


def list_group_timeline(
    session: Session, group_id: int, start_utc: datetime, end_utc: datetime
) -> list[dict]:
    """One dict per member device: `{device_id, name, points}` for `[start_utc, end_utc)`.

    Never merges points across devices (PROMPT.md §2 invariant 5) — each
    entry's `points` list holds only that one device_id's observations.
    Caller (routes_history.py) is responsible for the group-not-found 404.
    """
    members = session.execute(
        select(Device.device_id, Device.name)
        .join(DeviceGroup, DeviceGroup.device_id == Device.device_id)
        .where(DeviceGroup.group_id == group_id)
    ).all()

    result = []
    for device_id, name in members:
        obs = session.scalars(
            select(LocationObservation)
            .where(
                LocationObservation.device_id == device_id,
                LocationObservation.observed_at >= start_utc,
                LocationObservation.observed_at < end_utc,
            )
            .order_by(LocationObservation.observed_at)
        ).all()
        points = [
            {
                "lat": o.latitude_e7 / 1e7,
                "lon": o.longitude_e7 / 1e7,
                # Aware UTC already carries "+00:00"; a trailing "Z" makes it unparseable.
                "observed_at": o.observed_at.isoformat(),
                "accuracy_meters": o.accuracy_meters,
            }
            for o in obs
        ]
        result.append({"device_id": device_id, "name": name, "points": points})
    return result
