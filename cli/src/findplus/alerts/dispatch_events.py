"""Load pending place_events/group_place_events as dispatch_core dataclasses.

Purpose : Split out of dispatch.py (PRI rule 7's 300-line cap, pushed over by
          multi-target Telegram dispatch) -- this half owns only "what needs
          notifying"; dispatch.py owns matching, sending and recording.
Inputs  : place_events/group_place_events/left_behind rows not yet notified.
Outputs : DeviceEvent/GroupEvent/LeftBehindEvent dataclasses (dispatch_types.py).
Constraints: No caller-visible change -- dispatch.py re-exports
          load_pending_events so every existing `from findplus.alerts.
          dispatch import load_pending_events` call site is unchanged.
"""

from __future__ import annotations

from findplus.alerts.dispatch_core import DeviceEvent, GroupEvent, LeftBehindEvent, as_utc
from findplus.alerts.group_event_rows import pending_group_events

#: COALESCE(d.label, d.name): an alert names the tracker by its label (UAT U7).
_DEVICE_EVENTS_SQL = """SELECT pe.id, pe.place_id, p.name AS place_name, pe.device_id,
       COALESCE(d.label, d.name) AS device_name, pe.event_type, pe.observed_at, pe.fetched_at,
       pe.confidence
FROM place_events pe JOIN places p ON p.id = pe.place_id
JOIN devices d ON d.device_id = pe.device_id
WHERE pe.notified_at IS NULL ORDER BY pe.observed_at ASC"""

_MEMBERSHIP_SQL = """SELECT dg.group_id, g.kind FROM device_group dg
JOIN groups g ON g.id = dg.group_id WHERE dg.device_id = :device_id"""


def load_pending_events(session) -> list[DeviceEvent | GroupEvent | LeftBehindEvent]:
    """Un-notified place_events, group_place_events and left-behind episodes.

    notified_at IS NULL is the hand-off from the ingest-time geofence, group
    and person hooks. A quorum GroupEvent's `note` is rebuilt from the stored
    counts; a person event carries its own (alerts/group_event_rows.py).
    """
    from findplus.alerts.dispatch_left_behind import pending_left_behind

    return [
        *_load_device_events(session),
        *pending_group_events(session),
        *pending_left_behind(session),
    ]


def _load_device_events(session) -> list[DeviceEvent]:
    from sqlalchemy import text

    events: list[DeviceEvent] = []
    for row in session.execute(text(_DEVICE_EVENTS_SQL)).all():
        memberships = session.execute(text(_MEMBERSHIP_SQL), {"device_id": row.device_id}).all()
        events.append(
            DeviceEvent(
                place_event_id=row.id,
                place_id=row.place_id,
                place_name=row.place_name,
                device_id=row.device_id,
                device_name=row.device_name,
                event_type=row.event_type,
                observed_at=as_utc(row.observed_at),
                fetched_at=as_utc(row.fetched_at),
                confidence=row.confidence,
                group_ids=[m.group_id for m in memberships],
                person_group_ids=[m.group_id for m in memberships if m.kind in ("person", "pet")],
            )
        )
    return events
