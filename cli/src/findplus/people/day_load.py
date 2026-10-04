"""Load one person's day from the database and shape the summary payload (spec § 7.2).

Purpose    : The DB half of people/day.py, shared by the API, CLI, MCP and the
             digest: read the day's sightings (suspect ones set aside and
             counted), person events, left-behind episodes and places, run the
             pure algorithm, and return the documented JSON shape.
Inputs     : An open Session, a person Group, a local date, a ZoneInfo, `now`.
Outputs    : `day_payload(...)` -> dict (see the keys in `day_payload`).
Constraints: Read only. Raw sightings are never altered. Sightings are never
             merged across trackers (invariant 5): each line cites its own.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from findplus import honesty
from findplus.db.models import GroupPlaceEvent, LocationObservation, Place, PlaceEvent
from findplus.db.models_people import LeftBehind
from findplus.device_labels import unique_names
from findplus.people import _quality, repo
from findplus.people.day import build_day, shown_episode
from findplus.people.day_text import day_t
from findplus.people.day_types import DayInput, EpisodeIn, EventIn, NowIn, PlaceIn, TrackerIn
from findplus.people.describe import labels_for
from findplus.people.inputs import infer_person, params_for, trackers_of
from findplus.quality.fix import Fix
from findplus.timeline import day_bounds_utc

#: Hours of sightings loaded before midnight, to know where the night began.
ANCHOR_HOURS = 12


def _fixes(session: Session, device_ids: list[str], start: datetime, end: datetime):
    """(fixes by device without suspect or clock-skewed ones, wrong count inside the
    day, the day's sightings held for a second sighting, oldest first).

    A sighting claiming a time after its first fetch + 5 min comes from a fast
    clock: left out silently, as the person engine does (people/_quality.py)."""
    lo = start - timedelta(hours=ANCHOR_HOURS)
    rows = session.scalars(
        select(LocationObservation)
        .where(
            LocationObservation.device_id.in_(device_ids),
            LocationObservation.observed_at >= lo,
            LocationObservation.observed_at < end,
        )
        .order_by(LocationObservation.observed_at, LocationObservation.id)
    ).all()
    suspect = _quality.suspect_ids(session, device_ids, lo, end)
    by_dev: dict[str, list[Fix]] = {d: [] for d in device_ids}
    for o in rows:
        if o.id in suspect or _quality.skewed(o.observed_at, o.first_fetched_at):
            continue  # flagged, or from a fast clock: the engine ignores both, so does the day
        by_dev[o.device_id].append(
            Fix(o.id, o.observed_at, o.latitude, o.longitude, o.accuracy_meters)
        )
    held_ids = _quality.held_ids(session, device_ids, start, end)
    day = [o for o in rows if o.id in suspect and start <= o.observed_at < end]
    held = tuple(
        Fix(o.id, o.observed_at, o.latitude, o.longitude, o.accuracy_meters)
        for o in day
        if o.id in held_ids
    )
    wrong = sum(1 for o in day if o.id not in held_ids)
    return {d: tuple(v) for d, v in by_dev.items()}, wrong, held


def _events(session: Session, group_id: int, start: datetime, end: datetime) -> list[EventIn]:
    rows = session.scalars(
        select(GroupPlaceEvent)
        .where(
            GroupPlaceEvent.group_id == group_id,
            GroupPlaceEvent.basis == "person",
            GroupPlaceEvent.observed_at >= start,
            GroupPlaceEvent.observed_at < end,
        )
        .order_by(GroupPlaceEvent.observed_at, GroupPlaceEvent.id)
    ).all()
    out = []
    for r in rows:
        try:
            ids = [int(i) for i in json.loads(r.member_event_ids or "[]")]
        except (ValueError, TypeError):
            ids = []
        devices = (
            session.scalars(select(PlaceEvent.device_id).where(PlaceEvent.id.in_(ids))).all()
            if ids
            else []
        )
        out.append(
            EventIn(
                r.observed_at,
                r.event_type,
                r.place_id,
                r.lead_device_id,
                tuple(dict.fromkeys(devices)),
                r.confidence or "high",
            )
        )
    return out


def episode_dict(row: LeftBehind, names: dict[str, str], places: dict[int, str]) -> dict:
    """One left-behind episode as JSON (same keys as GET /api/people/{id}/left-behind)."""

    def iso(v):
        return v.isoformat() if v else None

    return {
        "id": row.id,
        "person_id": row.group_id,
        "device_id": row.device_id,
        "device_name": names.get(row.device_id, row.device_id),
        "place_id": row.place_id,
        "place_name": places.get(row.place_id) if row.place_id else None,
        "latitude": row.anchor_lat_e7 / 1e7,
        "longitude": row.anchor_lon_e7 / 1e7,
        "state": row.state,
        "started_observed_at": iso(row.started_observed_at),
        "confirmed_at": iso(row.confirmed_at),
        "cleared_at": iso(row.cleared_at),
        "clear_reason": row.clear_reason,
        "notified_at": iso(row.notified_at),
    }


def _episodes(
    session: Session, group_id: int, start, end, places
) -> list[tuple[LeftBehind, EpisodeIn]]:
    rows = session.scalars(
        select(LeftBehind)
        .where(
            LeftBehind.group_id == group_id,
            LeftBehind.confirmed_at.is_not(None),
            LeftBehind.started_observed_at < end,
        )
        .order_by(LeftBehind.started_observed_at)
    ).all()
    rows = [r for r in rows if r.cleared_at is None or r.cleared_at >= start]
    return [
        (
            r,
            EpisodeIn(
                r.id,
                r.device_id,
                r.place_id,
                places.get(r.place_id),
                r.started_observed_at,
                r.confirmed_at,
                r.cleared_at,
                r.clear_reason,
                r.anchor_lat_e7 / 1e7,
                r.anchor_lon_e7 / 1e7,
                r.state,
                r.notified_at,
            ),
        )
        for r in rows
    ]


def _now_in(fix) -> NowIn:
    return NowIn(
        fix.confidence,
        fix.place_id,
        fix.place_name,
        fix.relation,
        fix.distance_m,
        fix.reference_place,
        fix.observed_at,
        fix.lead_device_id,
        tuple(fix.supporters),
        fix.lat,
        fix.lon,
    )


def load_input(session: Session, group, day: date, tz: ZoneInfo, now: datetime):
    """(DayInput, left-behind rows, trackers, the person's now-answer or None)."""
    start, end = day_bounds_utc(day, tz)
    names = unique_names(session)
    trackers = trackers_of(session, group.id, names)
    labels = labels_for(trackers, group.name)
    fixes, suspect, held = _fixes(session, [t.device_id for t in trackers], start, end)
    place_rows = list(session.scalars(select(Place).order_by(Place.name)).all())
    places = tuple(
        PlaceIn(p.id, p.name, p.kind, p.latitude_e7 / 1e7, p.longitude_e7 / 1e7, p.radius_meters)
        for p in place_rows
    )
    episodes = _episodes(session, group.id, start, end, {p.id: p.name for p in place_rows})
    now_fix = infer = None
    if start <= now < end:
        infer = infer_person(session, group, now, names)
        now_fix = _now_in(infer[0])
    inp = DayInput(
        name=group.name,
        day=day,
        tz=tz,
        now=now,
        stale_after_minutes=params_for(group).stale_after_minutes,
        trackers=tuple(
            TrackerIn(t.device_id, t.name, t.role, labels[t.device_id], t.weight) for t in trackers
        ),
        fixes=fixes,
        suspect_count=suspect,
        held=held,
        events=tuple(_events(session, group.id, start, end)),
        episodes=tuple(e for _, e in episodes),
        places=places,
        now_fix=now_fix,
    )
    shown = [r for r, e in episodes if shown_episode({p.id: p for p in places}, e, start, end)]
    return inp, shown, trackers, infer


def _tracker_rows(inp: DayInput, window, trackers) -> list[dict]:
    labels = {x.device_id: x.label for x in inp.trackers}
    out = []
    for t in trackers:
        fx = window.get(t.device_id, [])
        out.append(
            {
                "device_id": t.device_id,
                "name": t.name,
                "role": t.role,
                "label": labels[t.device_id],
                "fixes": len(fx),
                "first_at": fx[0].t.strftime("%Y-%m-%dT%H:%M:%SZ") if fx else None,
                "last_at": fx[-1].t.strftime("%Y-%m-%dT%H:%M:%SZ") if fx else None,
            }
        )
    return out


def day_payload(
    session: Session, group, day: date, tz: ZoneInfo, now: datetime | None = None
) -> dict:
    """The GET /api/people/{id}/day body."""
    from findplus.people.day_ctx import make_ctx

    now = (now or datetime.now(UTC)).astimezone(UTC)
    inp, rows, trackers, infer = load_input(session, group, day, tz, now)
    result = build_day(inp)
    window = make_ctx(inp).window
    places = {p.id: p.name for p in inp.places}
    names = unique_names(session)
    now_body = repo.now_from(infer, group, now) if infer else None
    return {
        "person": {"id": group.id, "name": group.name},
        "date": day.isoformat(),
        "timezone": str(tz),
        "now": now_body,
        "heading": day_t("heading", name=group.name),
        "lines": [line.to_dict(tz) for line in result.lines],
        "left_behind": [episode_dict(r, names, places) for r in rows],
        "suspect_count": inp.suspect_count,
        "held_count": len(inp.held),
        "suspect_text": result.suspect_text,
        "gaps": [
            {
                "start": g.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end": g.end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "start_local": g.start.astimezone(tz).isoformat(timespec="seconds"),
                "end_local": g.end.astimezone(tz).isoformat(timespec="seconds"),
                "minutes": g.minutes,
            }
            for g in result.gaps
        ],
        "trackers": _tracker_rows(inp, window, trackers),
        "lead_device_id": result.lead_device_id,
        "empty": result.empty,
        "label": honesty.TRIPS_APPROXIMATE,
    }
