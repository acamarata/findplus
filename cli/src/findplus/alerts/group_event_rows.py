"""group_place_events rows as GroupEvent dataclasses: one loader for every reader.

Purpose : Dispatch (pending rows), retry (one row by id) and the delivery log
          (a page of ids) each built GroupEvent from their own copy of the same
          SQL. Person events (spec § 5) added basis, note, kind and the lead
          tracker, so the three copies would have drifted; this is the one copy.
Inputs  : A session; either "pending" (notified_at IS NULL) or a list of ids.
Outputs : list[GroupEvent] in observed_at order.
Constraints: Read only. A quorum row's note is rebuilt from its stored counts
          (groups/quorum.group_event_note); a person row carries its own note.
          The lead's fetched_at is the first fetch of the lead tracker's sighting
          at the event's observed_at (people/crossing.py makes the event time a
          sighting of the lead), else of its first sighting after it, so
          "reported 4:31 PM" is a real time of the right tracker (r116 #9).
"""

from __future__ import annotations

from sqlalchemy import bindparam, text

from findplus.alerts.dispatch_core import GroupEvent, as_utc
from findplus.groups.quorum import group_event_note, stale_note_for_count

_SQL = """SELECT gpe.id, gpe.group_id, g.name AS group_name, g.kind AS group_kind, gpe.place_id,
       p.name AS place_name, gpe.event_type, gpe.observed_at, gpe.confidence,
       gpe.members_crossed, gpe.members_considered, gpe.members_stale,
       gpe.basis, gpe.note, gpe.lead_device_id, COALESCE(d.label, d.name) AS lead_name,
       (SELECT lo.first_fetched_at FROM location_observations lo
         WHERE lo.device_id = gpe.lead_device_id AND lo.observed_at >= gpe.observed_at
         ORDER BY lo.observed_at, lo.first_fetched_at LIMIT 1) AS lead_fetched_at
FROM group_place_events gpe JOIN groups g ON g.id = gpe.group_id
JOIN places p ON p.id = gpe.place_id
LEFT JOIN devices d ON d.device_id = gpe.lead_device_id
WHERE {where} ORDER BY gpe.observed_at ASC"""


def _to_event(row) -> GroupEvent:
    person = row.basis == "person"
    note = (
        (row.note or "")
        if person
        else group_event_note(
            crossed=row.members_crossed,
            considered=row.members_considered,
            event_type=row.event_type,
            place=row.place_name,
            stale_note=stale_note_for_count(row.members_stale),
        )
    )
    return GroupEvent(
        group_place_event_id=row.id,
        group_id=row.group_id,
        group_name=row.group_name,
        place_id=row.place_id,
        place_name=row.place_name,
        event_type=row.event_type,
        observed_at=as_utc(row.observed_at),
        confidence=row.confidence,
        note=note,
        members_crossed=row.members_crossed,
        members_considered=row.members_considered,
        members_stale=row.members_stale,
        basis=row.basis or "quorum",
        group_kind=row.group_kind or "set",
        lead_device_id=row.lead_device_id,
        lead_name=row.lead_name,
        fetched_at=as_utc(row.lead_fetched_at) if person else None,
    )


def pending_group_events(session) -> list[GroupEvent]:
    """Every group_place_events row not yet notified."""
    rows = session.execute(text(_SQL.format(where="gpe.notified_at IS NULL"))).all()
    return [_to_event(r) for r in rows]


def group_events_by_ids(session, ids: list[int]) -> dict[int, GroupEvent]:
    """The rows with these ids, notified or not; a missing id is simply absent."""
    if not ids:
        return {}
    stmt = text(_SQL.format(where="gpe.id IN :ids")).bindparams(bindparam("ids", expanding=True))
    return {r.id: _to_event(r) for r in session.execute(stmt, {"ids": list(ids)}).all()}
