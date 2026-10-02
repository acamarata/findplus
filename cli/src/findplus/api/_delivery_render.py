"""Render queued native deliveries' notification title and body on read.

Purpose    : GET /api/alerts/deliveries hands the desktop poller a title/body
             pair per native row. The text is computed on every read rather than
             stored on the row, so renaming a place or a device is reflected in
             an alert that has not been shown yet, with no backfill.
Inputs     : A session and the page's `(event_kind, event_id)` pairs.
Outputs    : One (text, body) tuple per pair -- the first line of the rendered
             alert and the rest of it -- or (None, None) when the source event
             is gone. `batch_delivery_text_bodies` resolves an entire page in
             one query per kind (device, group), never one query per row
             (CF-P2-16); left-behind episodes are re-inferred per row, and
             are rare.
Constraints: Never raises. Retention prunes place_events and group_place_events
             (service/retention.py) while a delivery row survives, so a missing
             event is an expected state, not a 500.
"""

from __future__ import annotations

import datetime

from findplus.alerts.dispatch_core import DeviceEvent, render_message
from findplus.alerts.group_event_rows import group_events_by_ids
from findplus.db.models import Device, Place, PlaceEvent

_RenderKey = tuple[str, int]
_RenderResult = tuple[str | None, str | None]


def _batch_device_events(session, event_ids: list[int]) -> dict[int, DeviceEvent]:
    """One query resolving every device-kind event id in `event_ids`."""
    if not event_ids:
        return {}
    rows = (
        session.query(PlaceEvent, Place.name, Device.name, Device.label)
        .join(Place, Place.id == PlaceEvent.place_id)
        .join(Device, Device.device_id == PlaceEvent.device_id)
        .filter(PlaceEvent.id.in_(event_ids))
        .all()
    )
    out: dict[int, DeviceEvent] = {}
    for event, place_name, device_name, device_label in rows:
        out[event.id] = DeviceEvent(
            place_event_id=event.id,
            place_id=event.place_id,
            place_name=place_name,
            device_id=event.device_id,
            # The label the user gave the tracker, falling back to the
            # provider's own name (UAT U7): a native notification renders
            # this same text on read.
            device_name=device_label or device_name,
            event_type=event.event_type,
            observed_at=event.observed_at,
            fetched_at=event.fetched_at,
            confidence=event.confidence,
            group_ids=[],
        )
    return out


def batch_delivery_text_bodies(session, items: list[_RenderKey]) -> dict[_RenderKey, _RenderResult]:
    """text/body for many `(event_kind, event_id)` pairs, in O(1) queries.

    Same per-item contract as a single-row render: a missing or unrenderable
    source event yields (None, None) for that item only, never raises, and
    never affects any other item in the page.
    """
    from findplus.alerts.dispatch_left_behind import left_behind_by_ids

    def ids(kind: str) -> list[int]:
        return [event_id for event_kind, event_id in items if event_kind == kind]

    by_kind = {
        "device": _batch_device_events(session, ids("device")),
        "group": group_events_by_ids(session, ids("group")),
        "left_behind": left_behind_by_ids(session, ids("left_behind")),
    }
    now = datetime.datetime.now(datetime.UTC)

    out: dict[_RenderKey, _RenderResult] = {}
    for event_kind, event_id in items:
        event = by_kind.get(event_kind, {}).get(event_id)
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
