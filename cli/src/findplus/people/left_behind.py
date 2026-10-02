"""Left-behind trackers: the bag stayed at School while the shoes went home (spec § 4).

Purpose : Per (person, tracker): with_person -> apart_pending -> left_behind ->
          cleared, stored in `left_behind` (no row = with the person). An
          episode is confirmed only after `APART_MINUTES` and two newer
          sightings of the person, and alerts once (alerts/dispatch_events.py
          loads confirmed, un-notified episodes away from Home).
Inputs  : The PersonFix the event engine just computed, the member trackers,
          the saved places, `as_of`.
Outputs : Rows inserted/updated/deleted in `left_behind`. Nothing else.
Constraints: A pending episode is dropped by one contrary sighting; a confirmed
          one only clears when the tracker moves (carried), the person comes
          back (rejoined), the tracker goes stale (stale: "no recent sighting",
          never "still left behind") or the owner says "I know" (dismissed,
          which silences that tracker at that place for the local day). A
          stale-cleared episode resumes, already notified, when the tracker
          reports again from the same spot.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from findplus.db.models import LocationObservation, PlaceState
from findplus.db.models_people import LeftBehind
from findplus.geo import haversine_meters
from findplus.people import _quality
from findplus.people.infer import MemberScore, PersonFix, PlaceRef
from findplus.places.geofence import exit_margin

APART_MINUTES = 20
MIN_APART_METERS = 300.0
#: Newer sightings of the person's other trackers needed before confirming.
CONFIRM_SIGHTINGS = 2
OPEN_STATES = ("apart_pending", "left_behind")


def apart_threshold(place: PlaceRef | None) -> float:
    """max(300 m, radius + exit margin) around the place the tracker sits in."""
    if place is None:
        return MIN_APART_METERS
    return max(MIN_APART_METERS, place.radius_meters + exit_margin(place.radius_meters))


def _distance(a_lat: float, a_lon: float, fix: PersonFix) -> float:
    return haversine_meters(a_lat, a_lon, fix.lat, fix.lon)


def is_apart(
    score: MemberScore, fix: PersonFix, weights: dict[str, float], threshold: float
) -> bool:
    """Every entry condition of spec § 4 for one tracker, as of this fix."""
    if score.motion == "stale" or not score.still or score.fix is None:
        return False
    if fix.confidence != "likely" or score.device_id in fix.supporters or fix.lat is None:
        return False
    if not any(weights.get(d, 0.0) >= score.weight for d in fix.supporters):
        return False
    return _distance(score.fix.lat, score.fix.lon, fix) > threshold


def clear_reason(row: LeftBehind, score: MemberScore, fix: PersonFix, threshold: float):
    """Why an open episode ends now, or None to keep it (carried/rejoined/stale)."""
    if score.motion == "stale" or score.fix is None:
        return "stale"
    lat, lon = row.anchor_lat_e7 / 1e7, row.anchor_lon_e7 / 1e7
    acc = max(150.0, 2 * (score.fix.accuracy_meters or 100.0))
    if haversine_meters(lat, lon, score.fix.lat, score.fix.lon) > acc:
        return "carried"
    confident = fix.lat is not None and fix.confidence in ("likely", "probably")
    if confident and haversine_meters(lat, lon, fix.lat, fix.lon) <= threshold:
        return "rejoined"
    return None


def _anchor_place(session: Session, device_id: str, places: list[PlaceRef]) -> PlaceRef | None:
    inside = set(
        session.scalars(
            select(PlaceState.place_id).where(
                PlaceState.device_id == device_id, PlaceState.state == "inside"
            )
        ).all()
    )
    hits = [p for p in places if p.id in inside]
    return min(hits, key=lambda p: (p.radius_meters, p.name)) if hits else None


def _newer_sightings(session: Session, fix: PersonFix, device_id: str, since) -> int:
    """Newer sightings OF THE PERSON: non-suspect fixes of the trackers that
    place them now (the best cluster), skipping parked ones. A bike and spare
    shoes reporting from the garage are not sightings of the person (r116 #11)."""
    motion = {m.device_id: m.motion for m in fix.members}
    carriers = [d for d in fix.supporters if d != device_id and motion.get(d) != "parked"]
    if not carriers:
        return 0
    ids = session.scalars(
        select(LocationObservation.id).where(
            LocationObservation.device_id.in_(carriers), LocationObservation.observed_at > since
        )
    ).all()
    if not ids:
        return 0
    newest = session.scalar(select(func.max(LocationObservation.observed_at)).where(
        LocationObservation.id.in_(ids)))  # fmt: skip
    suspect = _quality.suspect_ids(session, carriers, since, newest)
    return sum(1 for i in ids if i not in suspect)


def _dismissed_today(session: Session, group_id: int, device_id: str, place_id, as_of) -> bool:
    """'I know' silences this tracker at this place for the rest of the local day."""
    from findplus.alerts.dispatch_core import local_zone

    zone = local_zone()
    day = as_of.astimezone(zone).date()
    rows = session.scalars(
        select(LeftBehind.cleared_at).where(
            LeftBehind.group_id == group_id,
            LeftBehind.device_id == device_id,
            LeftBehind.place_id.is_(place_id)
            if place_id is None
            else LeftBehind.place_id == place_id,
            LeftBehind.clear_reason == "dismissed",
        )
    ).all()
    return any(c is not None and c.astimezone(zone).date() == day for c in rows)


def _same_anchor(row: LeftBehind, score: MemberScore) -> bool:
    acc = max(150.0, 2 * (score.fix.accuracy_meters or 100.0))
    lat, lon = row.anchor_lat_e7 / 1e7, row.anchor_lon_e7 / 1e7
    return haversine_meters(lat, lon, score.fix.lat, score.fix.lon) <= acc


def _resume_after_stale(session: Session, group_id: int, device_id: str, score, pid) -> bool:
    """A tracker that went quiet and reports again from the same spot is the
    same episode: reopen it with its notified_at kept, so it never alerts
    twice (spec § 4 "once per episode", review r116 #6)."""
    last = session.scalars(
        select(LeftBehind)
        .where(LeftBehind.group_id == group_id, LeftBehind.device_id == device_id)
        .order_by(LeftBehind.id.desc())
        .limit(1)
    ).first()
    if last is None or last.clear_reason != "stale" or last.place_id != pid:
        return False
    if not _same_anchor(last, score):
        return False
    last.state, last.cleared_at, last.clear_reason = "left_behind", None, None
    return True


def _open(session: Session, group_id: int, device_id: str, score, place, as_of) -> None:
    pid = place.id if place else None
    if _dismissed_today(session, group_id, device_id, pid, as_of):
        return
    if _resume_after_stale(session, group_id, device_id, score, pid):
        return
    session.add(
        LeftBehind(group_id=group_id, device_id=device_id, place_id=pid,
                   anchor_lat_e7=score.fix.latitude_e7, anchor_lon_e7=score.fix.longitude_e7,
                   state="apart_pending", started_observed_at=as_of)
    )  # fmt: skip


def _advance(session, row, score, fix, ctx) -> None:
    """Move one open episode: confirm, clear, drop or keep."""
    _, weights, place, as_of = ctx
    threshold = apart_threshold(place)
    reason = clear_reason(row, score, fix, threshold)
    if row.state == "apart_pending":
        if reason is not None or (fix.confidence == "likely" and score.device_id in fix.supporters):
            session.delete(row)  # one contrary sighting resets a pending episode
            return
        old_enough = as_of - row.started_observed_at >= timedelta(minutes=APART_MINUTES)
        seen = _newer_sightings(session, fix, row.device_id, row.started_observed_at)
        if old_enough and seen >= CONFIRM_SIGHTINGS and is_apart(score, fix, weights, threshold):
            row.state, row.confirmed_at = "left_behind", as_of
        return
    if reason is not None:
        row.state, row.cleared_at, row.clear_reason = "cleared", as_of, reason


def evaluate(session: Session, group, fix: PersonFix, trackers, places, as_of: datetime) -> None:
    """Advance every member tracker's left-behind state by one person evaluation."""
    open_rows = {
        r.device_id: r
        for r in session.scalars(
            select(LeftBehind).where(
                LeftBehind.group_id == group.id, LeftBehind.state.in_(OPEN_STATES)
            )
        ).all()
    }
    weights = {t.device_id: t.weight for t in trackers}
    ids = [t.device_id for t in trackers]
    for score in fix.members:
        place = _anchor_place(session, score.device_id, places)
        row = open_rows.get(score.device_id)
        if row is not None:
            _advance(session, row, score, fix, (ids, weights, place, as_of))
        elif is_apart(score, fix, weights, apart_threshold(place)):
            _open(session, group.id, score.device_id, score, place, as_of)
    session.flush()


def dismiss(session: Session, group_id: int, left_behind_id: int, now: datetime | None = None):
    """The owner's "I know": clear the episode and silence it for the local day."""
    row = session.get(LeftBehind, left_behind_id)
    if row is None or row.group_id != group_id:
        raise ValueError(f"left-behind episode {left_behind_id} not found")
    if row.state in OPEN_STATES:
        row.state, row.clear_reason = "cleared", "dismissed"
        row.cleared_at = now or datetime.now(UTC)
        session.flush()
    return row
