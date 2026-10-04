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
from findplus.device_labels import unique_names

#: COALESCE(d.label, d.name): an alert names the tracker by its label (UAT U7); the loader
#: then swaps in device_labels.unique_names so same-named trackers differ (O11).
_DEVICE_EVENTS_SQL = """SELECT pe.id, pe.place_id, p.name AS place_name, pe.device_id,
       COALESCE(d.label, d.name) AS device_name, pe.event_type, pe.observed_at, pe.fetched_at,
       pe.confidence
FROM place_events pe JOIN places p ON p.id = pe.place_id
JOIN devices d ON d.device_id = pe.device_id
WHERE pe.notified_at IS NULL ORDER BY pe.observed_at ASC"""

_MEMBERSHIP_SQL = """SELECT dg.group_id, g.kind FROM device_group dg
JOIN groups g ON g.id = dg.group_id WHERE dg.device_id = :device_id"""

#: Person groups of this tracker with their own event for the same place and
#: type within PERSON_EVENT_WINDOW minutes of the device crossing.
_PERSON_EVENT_SQL = """SELECT DISTINCT gpe.group_id FROM group_place_events gpe
JOIN device_group dg ON dg.group_id = gpe.group_id
WHERE dg.device_id = :device_id AND gpe.basis = 'person' AND gpe.place_id = :place_id
  AND gpe.event_type = :event_type AND gpe.observed_at BETWEEN :lo AND :hi"""
PERSON_EVENT_WINDOW = 30


def load_pending_events(session) -> list[DeviceEvent | GroupEvent | LeftBehindEvent]:
    """Un-notified place_events, group_place_events and left-behind episodes.

    notified_at IS NULL is the hand-off from the ingest-time geofence, group
    and person hooks. A quorum GroupEvent's `note` is rebuilt from the stored
    counts; a person event carries its own (alerts/group_event_rows.py).
    """
    from findplus.alerts.dispatch_left_behind import pending_left_behind

    events = [
        *_load_device_events(session),
        *pending_group_events(session),
        *pending_left_behind(session),
    ]
    return sorted(events, key=_story_order)


#: At the same instant a departure reads before an arrival: "left Home", then
#: "arrived at Grandma's" (uat116 #14).
_TYPE_ORDER = {"EXIT": 0, "ENTER": 1}


def _story_order(event) -> tuple:
    return (as_utc(event.observed_at), _TYPE_ORDER.get(event.event_type, 2))


def _load_device_events(session) -> list[DeviceEvent]:
    from sqlalchemy import text

    events: list[DeviceEvent] = []
    shown = unique_names(session)
    for row in session.execute(text(_DEVICE_EVENTS_SQL)).all():
        memberships = session.execute(text(_MEMBERSHIP_SQL), {"device_id": row.device_id}).all()
        events.append(
            DeviceEvent(
                place_event_id=row.id,
                place_id=row.place_id,
                place_name=row.place_name,
                device_id=row.device_id,
                device_name=shown.get(row.device_id, row.device_name),
                event_type=row.event_type,
                observed_at=as_utc(row.observed_at),
                fetched_at=as_utc(row.fetched_at),
                confidence=row.confidence,
                group_ids=[m.group_id for m in memberships],
                person_group_ids=[m.group_id for m in memberships if m.kind in ("person", "pet")],
                person_event_group_ids=_person_event_groups(session, row),
                pet_group_ids=[m.group_id for m in memberships if m.kind == "pet"],
            )
        )
    return events


def _person_event_groups(session, row) -> list[int]:
    from datetime import UTC, timedelta

    from sqlalchemy import text

    at = as_utc(row.observed_at).astimezone(UTC).replace(tzinfo=None)
    window = timedelta(minutes=PERSON_EVENT_WINDOW)
    params = {"device_id": row.device_id, "place_id": row.place_id,
              "event_type": row.event_type, "lo": at - window, "hi": at + window}  # fmt: skip
    return [r.group_id for r in session.execute(text(_PERSON_EVENT_SQL), params).all()]
