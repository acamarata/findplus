"""Builders for the daily-summary scenarios (spec § 11, package C).

Purpose : Named synthetic days on top of the people scenario world
          (Home, School, Grandma's; Zaid with a bag, bike and two shoes), plus
          a one-call `summary()` that runs the real loader and algorithm.
Inputs  : The tmp_db-backed `session` fixture.
Outputs : n/a (test-only builders, never imported by cli/src).
Constraints: All fixes are synthetic; no network, no real account or state dir.
"""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from findplus.people.day_load import day_payload

from ._helpers import HOME, SCHOOL, Timeline, at

UTC_TZ = ZoneInfo("UTC")
DAY = date(2026, 9, 21)
ALL = ["zb", "zk", "zr", "zw"]


def summary(session, person, day=DAY, now=None, tz=UTC_TZ):
    """The day payload for `person`; `now` defaults to the morning after (a past day)."""
    now = now or at(6, 0, day=(day - DAY).days + 1)
    return day_payload(session, person, day, tz, now)


def texts(payload) -> list[str]:
    return [line["text"] for line in payload["lines"]]


NEAR_HOME = (HOME[0] + 0.0045, HOME[1])  # about 500 m north of Home, outside its circle


def school_day(tl: Timeline, carried=("zr", "zb"), parked=("zk", "zw")) -> Timeline:
    """Home 07:40, School 08:10, leave 15:00, Home 15:33 (the owner's sample day).

    Dense (5-minute) sightings around every crossing, so no time reads "around".
    """
    tl.stay([*carried, *parked], HOME, at(0, 0), at(7, 35), every=5)
    tl.walk(carried, HOME, SCHOOL, at(7, 35), at(8, 10), every=5)
    tl.stay(carried, SCHOOL, at(8, 15), at(14, 55), every=5)
    tl.walk(carried, SCHOOL, NEAR_HOME, at(14, 55), at(15, 30), every=5)
    tl.stay(carried, HOME, at(15, 33), at(17, 0), every=5)
    tl.stay(parked, HOME, at(7, 40), at(17, 0), every=5)
    return tl


def lean_school_day(tl: Timeline) -> Timeline:
    """The same day with far fewer sightings (fast): dense only around the crossings."""
    c, parked = ["zr", "zb"], ["zk", "zw"]
    tl.stay([*c, *parked], HOME, at(0, 0), at(0, 0))
    tl.stay([*c, *parked], HOME, at(7, 0), at(7, 35), every=5)
    tl.walk(c, HOME, SCHOOL, at(7, 35), at(8, 10), every=5)
    tl.stay(c, SCHOOL, at(8, 15), at(14, 15), every=40)
    tl.stay(c, SCHOOL, at(14, 50), at(14, 55), every=5)
    tl.walk(c, SCHOOL, NEAR_HOME, at(14, 55), at(15, 30), every=5)
    tl.stay(c, HOME, at(15, 33), at(17, 0), every=30)
    tl.stay(parked, HOME, at(7, 40), at(17, 0), every=180)
    return tl
