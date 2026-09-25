"""Load pending place_events/group_place_events as dispatch_core dataclasses.

Purpose : Split out of dispatch.py (PRI rule 7's 300-line cap, pushed over by
          multi-target Telegram dispatch) -- this half owns only "what needs
          notifying"; dispatch.py owns matching, sending and recording.
Inputs  : place_events/group_place_events rows with notified_at IS NULL.
Outputs : DeviceEvent/GroupEvent dataclasses (dispatch_core.py).
Constraints: No caller-visible change -- dispatch.py re-exports
          load_pending_events so every existing `from findplus.alerts.
          dispatch import load_pending_events` call site is unchanged.
"""

from __future__ import annotations

from findplus.alerts.dispatch_core import DeviceEvent, GroupEvent, as_utc
from findplus.groups.quorum import group_event_note, stale_note_for_count

#: COALESCE(d.label, d.name): an alert names the tracker by its label (UAT U7).
_DEVICE_EVENTS_SQL = """SELECT pe.id, pe.place_id, p.name AS place_name, pe.device_id,
       COALESCE(d.label, d.name) AS device_name, pe.event_type, pe.observed_at, pe.fetched_at,
       pe.confidence
FROM place_events pe JOIN places p ON p.id = pe.place_id
JOIN devices d ON d.device_id = pe.device_id
WHERE pe.notified_at IS NULL ORDER BY pe.observed_at ASC"""

_GROUP_EVENTS_SQL = """SELECT gpe.id, gpe.group_id, g.name AS group_name, gpe.place_id,
       p.name AS place_name, gpe.event_type, gpe.observed_at, gpe.confidence,
       gpe.members_crossed, gpe.members_considered, gpe.members_stale
FROM group_place_events gpe JOIN groups g ON g.id = gpe.group_id
JOIN places p ON p.id = gpe.place_id
WHERE gpe.notified_at IS NULL ORDER BY gpe.observed_at ASC"""


def load_pending_events(session) -> list[DeviceEvent | GroupEvent]:
    """Un-notified place_events/group_place_events rows, converted to dataclasses.

    notified_at IS NULL is the hand-off from the ingest-time geofence and
    group-quorum hooks. A GroupEvent's `note` is rebuilt from the stored counts
    (group_place_events has no note column) so the alert states how many tags
    actually crossed and how many were silent.
    """
    return [*_load_device_events(session), *_load_group_events(session)]


def _load_device_events(session) -> list[DeviceEvent]:
    from sqlalchemy import text

    events: list[DeviceEvent] = []
    for row in session.execute(text(_DEVICE_EVENTS_SQL)).all():
        group_ids = [
            r[0]
            for r in session.execute(
                text("SELECT group_id FROM device_group WHERE device_id = :device_id"),
                {"device_id": row.device_id},
            ).all()
        ]
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
                group_ids=group_ids,
            )
        )
    return events


def _load_group_events(session) -> list[GroupEvent]:
    from sqlalchemy import text

    events: list[GroupEvent] = []
    for row in session.execute(text(_GROUP_EVENTS_SQL)).all():
        events.append(
            GroupEvent(
                group_place_event_id=row.id,
                group_id=row.group_id,
                group_name=row.group_name,
                place_id=row.place_id,
                place_name=row.place_name,
                event_type=row.event_type,
                observed_at=as_utc(row.observed_at),
                confidence=row.confidence,
                note=group_event_note(
                    crossed=row.members_crossed,
                    considered=row.members_considered,
                    event_type=row.event_type,
                    place=row.place_name,
                    stale_note=stale_note_for_count(row.members_stale),
                ),
                members_crossed=row.members_crossed,
                members_considered=row.members_considered,
                members_stale=row.members_stale,
            )
        )
    return events
