"""Render a queued native delivery's notification title and body on read.

Purpose    : GET /api/alerts/deliveries hands the desktop poller a title/body
             pair per native row. The text is computed on every read rather than
             stored on the row, so renaming a place or a device is reflected in
             an alert that has not been shown yet, with no backfill.
Inputs     : A session, the delivery's event_kind and event_id.
Outputs    : (text, body) -- the first line of the rendered alert and the rest of
             it -- or (None, None) when the source event is gone.
Constraints: Never raises. Retention prunes place_events and group_place_events
             (service/retention.py) while a delivery row survives, so a missing
             event is an expected state, not a 500.
"""

from __future__ import annotations

import datetime

from findplus.alerts.dispatch_core import DeviceEvent, GroupEvent, render_message
from findplus.db.models import Device, Group, GroupPlaceEvent, Place, PlaceEvent
from findplus.groups.quorum import group_event_note, stale_note_for_count


def _device_event(session, event_id: int) -> DeviceEvent | None:
    row = (
        session.query(PlaceEvent, Place.name, Device.name)
        .join(Place, Place.id == PlaceEvent.place_id)
        .join(Device, Device.device_id == PlaceEvent.device_id)
        .filter(PlaceEvent.id == event_id)
        .first()
    )
    if row is None:
        return None
    event, place_name, device_name = row
    return DeviceEvent(
        place_event_id=event.id,
        place_id=event.place_id,
        place_name=place_name,
        device_id=event.device_id,
        device_name=device_name,
        event_type=event.event_type,
        observed_at=event.observed_at,
        fetched_at=event.fetched_at,
        confidence=event.confidence,
        group_ids=[],
    )


def _group_event(session, event_id: int) -> GroupEvent | None:
    row = (
        session.query(GroupPlaceEvent, Group.name, Place.name)
        .join(Group, Group.id == GroupPlaceEvent.group_id)
        .join(Place, Place.id == GroupPlaceEvent.place_id)
        .filter(GroupPlaceEvent.id == event_id)
        .first()
    )
    if row is None:
        return None
    event, group_name, place_name = row
    return GroupEvent(
        group_place_event_id=event.id,
        group_id=event.group_id,
        group_name=group_name,
        place_id=event.place_id,
        place_name=place_name,
        event_type=event.event_type,
        observed_at=event.observed_at,
        confidence=event.confidence,
        note=group_event_note(
            crossed=event.members_crossed,
            considered=event.members_considered,
            event_type=event.event_type,
            place=place_name,
            stale_note=stale_note_for_count(event.members_stale),
        ),
        members_crossed=event.members_crossed,
        members_considered=event.members_considered,
        members_stale=event.members_stale,
    )


def delivery_text_body(session, event_kind: str, event_id: int) -> tuple[str | None, str | None]:
    """The alert's first line and the rest of it, or (None, None) if it is gone."""
    try:
        event = (
            _device_event(session, event_id)
            if event_kind == "device"
            else _group_event(session, event_id)
        )
        if event is None:
            return None, None
        rendered = render_message(event, datetime.datetime.now(datetime.UTC))
    except Exception:  # a delivery list must not 500 over one unrenderable row
        return None, None
    first, _, rest = rendered.partition("\n")
    return first, rest or None
