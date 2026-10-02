"""Daily summary on DST days and on a day with a bad coordinate (spec § 11)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from findplus.people.day_load import day_payload
from findplus.quality.store import recompute

from ._day_helpers import ALL, NEAR_HOME, summary, texts
from ._helpers import DAY0, HOME, SCHOOL, Timeline, at, seed_person, seed_places

NY = ZoneInfo("America/New_York")


def local(day: date, hour: int, minute: int = 0) -> datetime:
    """A New York wall-clock time as an exact UTC instant (so stepping adds real minutes)."""
    return datetime.combine(day, time(hour, minute), tzinfo=NY).astimezone(UTC)


def _school_day_local(day: date) -> Timeline:
    c, parked = ["zr", "zb"], ["zk", "zw"]
    prev = date.fromordinal(day.toordinal() - 1)
    tl = Timeline().stay(ALL, HOME, local(prev, 22, 0), local(day, 0, 0), every=30)
    tl.stay(ALL, HOME, local(day, 0, 30), local(day, 7, 35), every=5)
    tl.walk(c, HOME, SCHOOL, local(day, 7, 35), local(day, 8, 10), every=5)
    tl.stay(c, SCHOOL, local(day, 8, 15), local(day, 14, 55), every=5)
    tl.walk(c, SCHOOL, NEAR_HOME, local(day, 14, 55), local(day, 15, 30), every=5)
    tl.stay(c, HOME, local(day, 15, 33), local(day, 23, 50), every=10)
    tl.stay(parked, HOME, local(day, 7, 40), local(day, 23, 50), every=30)
    return tl


@pytest.mark.parametrize(
    ("day", "hours"),
    [(date(2026, 11, 1), 25), (date(2026, 3, 8), 23)],
    ids=["fall_back_25h", "spring_forward_23h"],
)
def test_dst_day_runs_by_local_midnight(session, day, hours):
    seed_places(session)
    zaid = seed_person(session)
    _school_day_local(day).ingest(session)
    payload = day_payload(session, zaid, day, NY, local(date.fromordinal(day.toordinal() + 2), 6))
    assert texts(payload)[1:] == [
        "7:40 AM left Home",
        "8:10 AM arrived at School",
        "3:00 PM left School",
        "At Home from 3:33 PM",
    ]
    first = payload["lines"][0]
    assert first["kind"] == "overnight" and first["at"] == local(day, 0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    # The day's sightings run from local midnight to the next local midnight: 23 or 25 hours.
    tracker = next(t for t in payload["trackers"] if t["device_id"] == "zr")
    start = datetime.fromisoformat(tracker["first_at"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(tracker["last_at"].replace("Z", "+00:00"))
    assert start == local(day, 0, 0) and end == local(day, 23, 43)
    assert (
        local(date.fromordinal(day.toordinal() + 1), 0) - local(day, 0)
    ).total_seconds() == hours * 3600


def test_dst_day_leaves_the_next_days_first_sightings_out(session):
    day = date(2026, 3, 8)
    seed_places(session)
    zaid = seed_person(session)
    _school_day_local(day).ingest(session)
    Timeline().stay(
        ALL, HOME, local(date(2026, 3, 9), 0, 5), local(date(2026, 3, 9), 0, 40), every=5
    ).ingest(session)
    payload = day_payload(session, zaid, day, NY, local(date(2026, 3, 10), 6))
    zr = next(t for t in payload["trackers"] if t["device_id"] == "zr")
    assert zr["last_at"] == "2026-03-09T03:43:00Z"  # 23:43 EDT, not the 00:40 EDT that follows
    nxt = day_payload(session, zaid, date(2026, 3, 9), NY, local(date(2026, 3, 10), 6))
    assert texts(nxt)[0] == "Overnight at Home"


def test_a_teleport_sighting_is_left_out_and_counted(session):
    far = (HOME[0] + 3.75, HOME[1])  # about 417 km away, for one sighting
    seed_places(session)
    zaid = seed_person(session)
    tl = Timeline().stay(ALL, HOME, at(0, 0), at(9, 0), every=10)
    tl.add("zr", far, at(8, 5)).ingest(session)
    recompute(session, now=at(12, 0))
    payload = summary(session, zaid)
    assert payload["suspect_count"] == 1
    assert payload["suspect_text"] == "1 sighting looked wrong and was left out."
    assert texts(payload) == ["Overnight at Home", "Seen at Home through 9:00 AM"]
    assert not any(x["kind"] in ("left", "arrived", "stay") for x in payload["lines"])
    from findplus.people.day_render import render_text

    assert "1 sighting looked wrong and was left out." in render_text(payload)


def test_no_suspect_sightings_means_no_footer_sentence(session):
    seed_places(session)
    zaid = seed_person(session)
    Timeline().stay(ALL, HOME, at(0, 0), at(9, 0), every=10).ingest(session)
    recompute(session, now=at(12, 0))
    payload = summary(session, zaid)
    assert payload["suspect_count"] == 0 and payload["suspect_text"] is None
    assert DAY0.date() == date(2026, 9, 21)
