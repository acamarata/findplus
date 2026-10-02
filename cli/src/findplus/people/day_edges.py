"""The edges of a day summary: how it starts, what happened, where it ends (spec § 7.1).

Purpose    : The first line ("Overnight at Home" / "No sightings until 7:12 AM"),
             the person-event lines ("7:40 AM left Home"), and the last line
             ("Still at School (seen 3:58 PM)" only on fresh data, else "Last seen
             near School at 3:58 PM; nothing since").
Inputs     : A Ctx (people/day_ctx.py).
Outputs    : Lines, each with the trackers that back it and a confidence.
Constraints: Pure. A time is prefixed "around" when the sightings that bound it
             are over 10 minutes apart. Never "still at" on stale data.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from findplus.people.day_ctx import Ctx
from findplus.people.day_text import around, clock, day_t
from findplus.people.day_types import EventIn, Line
from findplus.people.describe import place_text


def time(ctx: Ctx, t: datetime, approx: bool) -> str:
    text = clock(t, ctx.tz)
    return around(text) if approx else text


def home_ids(ctx: Ctx) -> set[int]:
    return {p.id for p in ctx.places.values() if p.kind == "home"}


def first_line(ctx: Ctx) -> Line | None:
    """ "Overnight at Home" or "No sightings until 7:12 AM" (spec § 7.1 step 4)."""
    inp = ctx.inp
    first = min(
        (f for fx in ctx.window.values() for f in fx), key=lambda f: (f.t, f.id), default=None
    )
    if first is None:
        return None
    homes = home_ids(ctx)
    stale = timedelta(minutes=inp.stale_after_minutes)
    before = {d: [f for f in fx if f.t <= ctx.start] for d, fx in inp.fixes.items()}
    before = {d: fx[-1] for d, fx in before.items() if fx}
    fresh = {d: f for d, f in before.items() if ctx.start - f.t <= stale}
    home_at = {d: ctx.place_at(f) for d, f in (fresh or before).items()}
    at_home = [d for d, p in home_at.items() if p and p.id in homes]
    first_place = ctx.place_at(first)
    bracket = bool(at_home) and not fresh and first_place is not None and first_place.id in homes
    if at_home and (fresh or bracket):
        place = home_at[at_home[0]]
        return Line(
            "overnight",
            ctx.start,
            day_t("overnight", place=place.name),
            evidence=tuple(at_home),
            via=ctx.via(at_home),
            confidence="high" if fresh else "medium",
            place_id=place.id,
            place_name=place.name,
            lat=place.lat,
            lon=place.lon,
        )
    when = clock(first.t, ctx.tz)
    return Line(
        "no_sightings",
        ctx.start,
        day_t("noSightingsUntil", time=when),
        time=when,
        end=first.t,
        confidence="high",
    )


def _event_line(ctx: Ctx, e: EventIn, folded: bool) -> Line | None:
    place = ctx.places.get(e.place_id)
    if place is None:
        return None
    ids = tuple(dict.fromkeys([*([e.lead_device_id] if e.lead_device_id else []), *e.evidence]))
    approx = ctx.around(e.at, ids)
    when = time(ctx, e.at, approx)
    if e.event_type == "EXIT":
        kind, text = "left", day_t("left", time=when, place=place.name)
    elif folded:
        kind, text = "at_home_from", day_t("atFrom", place=place.name, time=when)
    else:
        kind, text = "arrived", day_t("arrived", time=when, place=place.name)
    fix = ctx.fix_near(e.lead_device_id, e.at)
    lat, lon = (fix.lat, fix.lon) if fix else (place.lat, place.lon)
    return Line(
        kind,
        e.at,
        text,
        time=when,
        evidence=ids,
        via=ctx.via(ids),
        approximate=approx,
        confidence="high" if e.confidence == "high" else "medium",
        place_id=place.id,
        place_name=place.name,
        lat=lat,
        lon=lon,
    )


def event_lines(ctx: Ctx) -> list[Line]:
    events = sorted((e for e in ctx.inp.events if ctx.start <= e.at < ctx.end), key=lambda e: e.at)
    homes = home_ids(ctx)
    lines = []
    for i, e in enumerate(events):
        later_exit = any(
            x.event_type == "EXIT" and x.place_id == e.place_id for x in events[i + 1 :]
        )
        folded = e.event_type == "ENTER" and e.place_id in homes and not later_exit
        line = _event_line(ctx, e, folded)
        if line:
            lines.append(line)
    return lines


def is_today(ctx: Ctx) -> bool:
    return ctx.start <= ctx.inp.now < ctx.end


def last_line(ctx: Ctx, has_home_fold: bool) -> Line | None:
    """Where the person is now (today only), or where the day's sightings ended."""
    now = ctx.inp.now_fix
    if not is_today(ctx) or now is None or now.observed_at is None or now.observed_at < ctx.start:
        return None
    seen = clock(now.observed_at, ctx.tz)
    age = ctx.inp.now - now.observed_at
    fresh = age <= timedelta(minutes=ctx.inp.stale_after_minutes) and now.confidence in (
        "likely",
        "probably",
    )
    ids = tuple(now.supporters) or ((now.lead_device_id,) if now.lead_device_id else ())
    base = dict(
        at=now.observed_at,
        time=seen,
        evidence=ids,
        via=ctx.via(ids),
        place_id=now.place_id,
        place_name=now.place_name,
        lat=now.lat,
        lon=now.lon,
    )
    conf = "high" if now.confidence == "likely" else "medium"
    if fresh and now.relation == "at" and now.place_name:
        home = now.place_id in home_ids(ctx)
        if home and has_home_fold:
            return None
        return Line(
            "still_at",
            text=day_t("stillAt", place=now.place_name, time=seen),
            confidence=conf,
            **base,
        )
    stale = age > timedelta(minutes=ctx.inp.stale_after_minutes) or now.confidence == "unknown"
    if now.place_name and now.relation in ("at", "near"):
        text = day_t("lastSeenNear", place=now.place_name, time=seen)
        text = text if stale else text.replace(day_t("nothingSince"), "")
    else:
        where = place_text(None, None, now.distance_m, now.reference_place)
        text = day_t("lastSeenAt", where=where, time=seen) + (
            day_t("nothingSince") if stale else ""
        )
    return Line("last_seen", text=text, confidence="low" if stale else conf, **base)


def seen_through(ctx: Ctx) -> Line | None:
    """A past or event-free day: the saved place the day's sightings ended in."""
    rows = ctx.person_fixes()
    if not rows:
        return None
    fix, device = rows[-1]
    place = ctx.place_at(fix)
    if place is None:
        return None
    when = clock(fix.t, ctx.tz)
    return Line(
        "seen_through",
        fix.t,
        day_t("seenThrough", place=place.name, time=when),
        time=when,
        evidence=(device,),
        via=ctx.via([device]),
        place_id=place.id,
        place_name=place.name,
        lat=fix.lat,
        lon=fix.lon,
    )
