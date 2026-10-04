"""What a rule would have sent over the last day (a dry run).

Purpose : Let someone see a rule work before they trust it. Replays the
          arrivals and departures Find+ already recorded against a rule that
          is being built (or an existing one) and says which would have
          produced a message, and which the cooldown would have held back.
Inputs  : An open Session, a dispatch_core.Rule, "now", and a window in hours.
Outputs : A list of dicts, oldest first: when, what, and whether it would send.
Constraints: Read-only: nothing is sent, recorded or marked notified. Uses the
          same `match()` and cooldown window dispatch.py uses, so the preview
          cannot disagree with real delivery about who matches. It does not
          know whether a channel is reachable right now; the Send test button
          answers that.
"""

from __future__ import annotations

import datetime

from sqlalchemy import text

from findplus.alerts.dispatch_core import DeviceEvent, GroupEvent, Rule, as_utc, match
from findplus.device_labels import unique_names
from findplus.groups.quorum import group_event_note, stale_note_for_count

_DEVICE_SQL = """SELECT pe.id, pe.place_id, p.name AS place_name, pe.device_id,
       COALESCE(d.label, d.name) AS device_name, pe.event_type, pe.observed_at,
       pe.fetched_at, pe.confidence
FROM place_events pe JOIN places p ON p.id = pe.place_id
JOIN devices d ON d.device_id = pe.device_id
WHERE pe.observed_at >= :since"""

_GROUP_SQL = """SELECT gpe.id, gpe.group_id, g.name AS group_name, gpe.place_id,
       p.name AS place_name, gpe.event_type, gpe.observed_at, gpe.confidence,
       gpe.members_crossed, gpe.members_considered, gpe.members_stale
FROM group_place_events gpe JOIN groups g ON g.id = gpe.group_id
JOIN places p ON p.id = gpe.place_id
WHERE gpe.observed_at >= :since"""


def _device_events(session, since: datetime.datetime) -> list[DeviceEvent]:
    shown = unique_names(session)
    return [
        DeviceEvent(
            place_event_id=r.id,
            place_id=r.place_id,
            place_name=r.place_name,
            device_id=r.device_id,
            device_name=shown.get(r.device_id, r.device_name),
            event_type=r.event_type,
            observed_at=as_utc(r.observed_at),
            fetched_at=as_utc(r.fetched_at),
            confidence=r.confidence,
            group_ids=[],
        )
        for r in session.execute(text(_DEVICE_SQL), {"since": since.replace(tzinfo=None)})
    ]


def _group_events(session, since: datetime.datetime) -> list[GroupEvent]:
    return [
        GroupEvent(
            group_place_event_id=r.id,
            group_id=r.group_id,
            group_name=r.group_name,
            place_id=r.place_id,
            place_name=r.place_name,
            event_type=r.event_type,
            observed_at=as_utc(r.observed_at),
            confidence=r.confidence,
            note=group_event_note(
                crossed=r.members_crossed,
                considered=r.members_considered,
                event_type=r.event_type,
                place=r.place_name,
                stale_note=stale_note_for_count(r.members_stale),
            ),
            members_crossed=r.members_crossed,
            members_considered=r.members_considered,
            members_stale=r.members_stale,
        )
        for r in session.execute(text(_GROUP_SQL), {"since": since.replace(tzinfo=None)})
    ]


def _line(event: DeviceEvent | GroupEvent) -> str:
    subject = event.device_name if isinstance(event, DeviceEvent) else event.group_name
    verb = "arrived at" if event.event_type == "ENTER" else "left"
    return f"{subject} {verb} {event.place_name}"


def would_have_fired(
    session, rule: Rule, now: datetime.datetime, hours: int = 24
) -> list[dict[str, object]]:
    """Every recorded crossing in the window that `rule` matches, oldest first.

    Each row: `observed_at` (ISO), `event_type`, `text`, `sends` (False when
    the rule's cooldown, counted per place from the last send, would hold it).
    """
    since = now - datetime.timedelta(hours=hours)
    events = [*_device_events(session, since), *_group_events(session, since)]
    events.sort(key=lambda e: e.observed_at)
    last_sent: dict[int, datetime.datetime] = {}
    out: list[dict[str, object]] = []
    for event in events:
        if not match([rule], event):
            continue
        prior = last_sent.get(event.place_id)
        held = (
            rule.cooldown_minutes > 0
            and prior is not None
            and event.observed_at < prior + datetime.timedelta(minutes=rule.cooldown_minutes)
        )
        if not held:
            last_sent[event.place_id] = event.observed_at
        out.append(
            {
                "observed_at": event.observed_at.isoformat(),
                "event_type": event.event_type,
                "text": _line(event),
                "sends": not held,
            }
        )
    return out
