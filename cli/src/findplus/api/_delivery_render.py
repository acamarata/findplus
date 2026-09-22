"""Render queued native deliveries' notification title and body on read.

Purpose    : GET /api/alerts/deliveries hands the desktop poller a title/body
             pair per native row. The text is computed on every read rather than
             stored on the row, so renaming a place or a device is reflected in
             an alert that has not been shown yet, with no backfill.
Inputs     : A session and the page's `(event_kind, event_id)` pairs.
Outputs    : One (text, body) tuple per pair -- the first line of the rendered
             alert and the rest of it -- or (None, None) when the source event
             is gone. `batch_delivery_text_bodies` resolves an entire page in
             at most two queries (one for the device kind, one for the group
             kind), never one query per row (CF-P2-16).
Constraints: Never raises. Retention prunes place_events and group_place_events
             (service/retention.py) while a delivery row survives, so a missing
             event is an expected state, not a 500.
"""

from __future__ import annotations

import datetime

from findplus.alerts.dispatch_core import DeviceEvent, GroupEvent, render_message
from findplus.db.models import Device, Group, GroupPlaceEvent, Place, PlaceEvent
from findplus.groups.quorum import group_event_note, stale_note_for_count

_RenderKey = tuple[str, int]
_RenderResult = tuple[str | None, str | None]


def _batch_device_events(session, event_ids: list[int]) -> dict[int, DeviceEvent]:
    """One query resolving every device-kind event id in `event_ids`."""
    if not event_ids:
        return {}
    rows = (
        session.query(PlaceEvent, Place.name, Device.name)
        .join(Place, Place.id == PlaceEvent.place_id)
        .join(Device, Device.device_id == PlaceEvent.device_id)
        .filter(PlaceEvent.id.in_(event_ids))
        .all()
    )
    out: dict[int, DeviceEvent] = {}
    for event, place_name, device_name in rows:
        out[event.id] = DeviceEvent(
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
    return out


def _batch_group_events(session, event_ids: list[int]) -> dict[int, GroupEvent]:
    """One query resolving every group-kind event id in `event_ids`."""
    if not event_ids:
        return {}
    rows = (
        session.query(GroupPlaceEvent, Group.name, Place.name)
        .join(Group, Group.id == GroupPlaceEvent.group_id)
        .join(Place, Place.id == GroupPlaceEvent.place_id)
        .filter(GroupPlaceEvent.id.in_(event_ids))
        .all()
    )
    out: dict[int, GroupEvent] = {}
    for event, group_name, place_name in rows:
        out[event.id] = GroupEvent(
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
    return out


def batch_delivery_text_bodies(session, items: list[_RenderKey]) -> dict[_RenderKey, _RenderResult]:
    """text/body for many `(event_kind, event_id)` pairs, in O(1) queries.

    Same per-item contract as a single-row render: a missing or unrenderable
    source event yields (None, None) for that item only, never raises, and
    never affects any other item in the page.
    """
    device_ids = [event_id for event_kind, event_id in items if event_kind == "device"]
    group_ids = [event_id for event_kind, event_id in items if event_kind != "device"]
    device_events = _batch_device_events(session, device_ids)
    group_events = _batch_group_events(session, group_ids)
    now = datetime.datetime.now(datetime.UTC)

    out: dict[_RenderKey, _RenderResult] = {}
    for event_kind, event_id in items:
        event = (
            device_events.get(event_id) if event_kind == "device" else group_events.get(event_id)
        )
        if event is None:
            out[(event_kind, event_id)] = (None, None)
            continue
        try:
            rendered = render_message(event, now)
        except Exception:  # a delivery list must not 500 over one unrenderable row
            out[(event_kind, event_id)] = (None, None)
            continue
        first, _, rest = rendered.partition("\n")
        out[(event_kind, event_id)] = (first, rest or None)
    return out


def delivery_text_body(session, event_kind: str, event_id: int) -> _RenderResult:
    """Single-row convenience wrapper over `batch_delivery_text_bodies`."""
    return batch_delivery_text_bodies(session, [(event_kind, event_id)])[(event_kind, event_id)]
