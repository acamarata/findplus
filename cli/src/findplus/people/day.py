"""The daily summary algorithm: one person, one local day, plain-words lines (spec § 7.1).

Purpose    : "Robin's day": when she left Home, arrived at School, left again
             and got home, plus unnamed stops of 15+ minutes, long gaps with no
             sightings, things left behind, and where she is now (today only).
Inputs     : A DayInput (rows already loaded; see people/day_load.py).
Outputs    : A DayResult with ordered Lines. Every line names the trackers that
             back it (`evidence`, `via`) and a confidence; a time is prefixed
             "around" when the sightings that bound it are over 10 minutes apart.
Constraints: Pure and deterministic. Never says "still at" on stale data, never
             invents a place (an unnamed spot is called one), never uses "just".
             Suspect sightings were removed upstream; only their count is shown.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from itertools import pairwise

from findplus.geo import haversine_meters
from findplus.people import messages as m
from findplus.people.day_ctx import Ctx, make_ctx
from findplus.people.day_edges import (
    event_lines,
    first_line,
    home_ids,
    is_today,
    last_line,
    seen_through,
)
from findplus.people.day_text import (
    around,
    clock,
    clock_range,
    date_label,
    day_t,
    suspect_sentence,
)
from findplus.people.day_types import DayInput, DayResult, EpisodeIn, GapOut, Line
from findplus.people.describe import place_text
from findplus.trips.segment import SegmentParams, segment

GAP_MINUTES = 90
STAY_MINUTES = 15


def _reference(ctx: Ctx, lat: float, lon: float):
    """(place name, metres) of the saved place to measure an unnamed spot from: Home first."""
    homes = [p for p in ctx.places.values() if p.kind == "home"] or list(ctx.places.values())
    ranked = sorted((haversine_meters(lat, lon, p.lat, p.lon), p.name) for p in homes)
    return (ranked[0][1], ranked[0][0]) if ranked else (None, None)


def _stay_lines(ctx: Ctx) -> list[Line]:
    """Lead-tracker stays of 15+ minutes outside every saved place."""
    fixes = ctx.window.get(ctx.lead or "", [])
    if not fixes:
        return []
    seg = segment(list(fixes), SegmentParams(dwell_min=STAY_MINUTES), ctx.lookup)
    lines = []
    for s in seg.stays:
        if s.place_id is not None or s.duration_min < STAY_MINUTES:
            continue
        ref, dist = _reference(ctx, s.lat, s.lon)
        where = place_text(None, None, dist, ref)
        approx = ctx.around(s.start, [ctx.lead]) or ctx.around_after(s.end, [ctx.lead])
        rng = clock_range(s.start, s.end, ctx.tz)
        rng = around(rng) if approx else rng
        lines.append(
            Line(
                "stay",
                s.start,
                day_t("stay", range=rng, where=where),
                time=rng,
                end=s.end,
                via=ctx.via([ctx.lead]),
                evidence=(ctx.lead,),
                approximate=approx,
                lat=s.lat,
                lon=s.lon,
            )
        )
    return lines


def _gaps(ctx: Ctx) -> list[GapOut]:
    """Spans over GAP_MINUTES with no sighting of the person, unless Home on both ends."""
    homes = home_ids(ctx)
    rows = ctx.person_fixes()
    out = []
    for (a, _), (b, _) in pairwise(rows):
        if (b.t - a.t) <= timedelta(minutes=GAP_MINUTES):
            continue
        pa, pb = ctx.place_at(a), ctx.place_at(b)
        if pa and pb and pa.id in homes and pb.id in homes:
            continue
        out.append(GapOut(a.t, b.t))
    return out


def _gap_lines(ctx: Ctx, gaps: list[GapOut]) -> list[Line]:
    return [
        Line(
            "gap",
            g.start,
            day_t("gap", range=clock_range(g.start, g.end, ctx.tz)),
            time=clock_range(g.start, g.end, ctx.tz),
            end=g.end,
        )
        for g in gaps
    ]


def _stamp(ctx: Ctx, t: datetime) -> str:
    local = t.astimezone(ctx.tz)
    if local.date() == ctx.inp.day:
        return clock(t, ctx.tz)
    return f"{date_label(local)}, {clock(t, ctx.tz)}"


def _episode_line(ctx: Ctx, ep: EpisodeIn) -> Line:
    what = ctx.labels.get(ep.device_id, ep.device_id)
    what = what[:1].upper() + what[1:]
    place = ep.place_name or m.t("now.unnamedSpot")
    if ep.cleared_at and ep.cleared_at < ctx.end:
        text = day_t(
            "stayedBehindUntil",
            what=what,
            place=place,
            time=_stamp(ctx, ep.started),
            until=_stamp(ctx, ep.cleared_at),
        )
    else:
        text = day_t("stayedBehind", what=what, place=place, time=_stamp(ctx, ep.started))
    return Line(
        "left_behind",
        max(ep.started, ctx.start),
        text,
        time=_stamp(ctx, ep.started),
        evidence=(ep.device_id,),
        via=ctx.via([ep.device_id]),
        confidence="high",
        place_id=ep.place_id,
        place_name=ep.place_name,
        lat=ep.lat,
        lon=ep.lon,
    )


def shown_episode(ctx_places, ep: EpisodeIn, start: datetime, end: datetime) -> bool:
    """A confirmed episode overlapping the day, away from Home (a bike at Home is not news)."""
    place = ctx_places.get(ep.place_id)
    if place is not None and place.kind == "home":
        return False
    if not ep.confirmed_at or ep.started >= end:
        return False
    return ep.cleared_at is None or ep.cleared_at >= start


def _left_lines(ctx: Ctx) -> list[Line]:
    return [
        _episode_line(ctx, ep)
        for ep in ctx.inp.episodes
        if shown_episode(ctx.places, ep, ctx.start, ctx.end)
    ]


def build_day(inp: DayInput) -> DayResult:
    """Every line of one person's local day, oldest first, plus gaps and the footer."""
    ctx = make_ctx(inp)
    has_data = any(ctx.window.values())
    events = event_lines(ctx) if has_data else []
    gaps = _gaps(ctx) if has_data else []
    lines = [x for x in (first_line(ctx) if has_data else None,) if x]
    lines += events + (_stay_lines(ctx) if has_data else []) + _gap_lines(ctx, gaps)
    lines += _left_lines(ctx)
    last = last_line(ctx, any(x.kind == "at_home_from" for x in events))
    if last:
        lines.append(last)
    elif has_data and not events and not is_today(ctx):
        through = seen_through(ctx)
        lines += [through] if through else []
    rank = {"overnight": 0, "no_sightings": 0}
    lines.sort(key=lambda x: (x.at, rank.get(x.kind, 1)))
    return DayResult(
        lines=lines,
        gaps=gaps,
        lead_device_id=ctx.lead,
        suspect_text=suspect_sentence(inp.suspect_count),
        empty=not lines,
    )
