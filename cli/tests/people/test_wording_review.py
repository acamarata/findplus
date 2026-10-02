"""Wording regressions from the 1.1.6 review: never read as more certain, never out of order."""

from __future__ import annotations

from datetime import UTC, datetime

from findplus.alerts.dispatch_core import GroupEvent
from findplus.alerts.render_person import render_person_message
from findplus.honesty import ALERTS_LATENCY

from ._day_helpers import summary, texts
from ._helpers import HOME, SCHOOL, Timeline, at, overnight, seed_person, seed_places

NOW = datetime(2026, 9, 21, 16, 0, tzinfo=UTC)


def _person_event(note: str, name: str = "Sam") -> GroupEvent:
    return GroupEvent(
        group_place_event_id=1, group_id=1, group_name=name, place_id=1, place_name="Home",
        event_type="EXIT", observed_at=NOW, confidence="medium", note=note, members_crossed=1,
        members_considered=4, members_stale=0, basis="person", group_kind="person",
        lead_device_id="zb", lead_name="X" * 120, fetched_at=NOW,
    )  # fmt: skip


def test_probably_never_drops_off_a_long_alert():
    """The note is "<stayed clause> (probably; ...)". When the whole note does
    not fit, the stayed clause may go, but the probably clause must stay, or a
    probably-level alert reads as certain."""
    stayed = "Sam's " + ", ".join(f"tracker {n}" for n in range(30)) + " stayed at Home."
    msg = render_person_message(_person_event(f"{stayed} (probably; only the bag reported)"), NOW)
    assert "(probably; only the bag reported)" in msg
    assert msg.endswith(ALERTS_LATENCY)
    assert len(msg) <= 400 + len(ALERTS_LATENCY) + 1


def test_probably_survives_even_a_very_long_name():
    msg = render_person_message(_person_event("(probably)", name="S" * 380), NOW)
    assert "(probably)" in msg and msg.endswith(ALERTS_LATENCY)


def test_a_departure_reads_before_the_arrival_at_the_same_minute(session):
    """Sam's quiet shoes report again from Home: "left School" and "At Home
    from" share 3:40 PM, and the day must read in that order."""
    seed_places(session)
    sam = seed_person(session)
    tl = Timeline()
    overnight(tl, ["zr", "zb", "zk", "zw"], end=at(7, 40))
    tl.walk(["zr"], HOME, SCHOOL, at(7, 40), at(8, 10))
    tl.stay(["zr"], SCHOOL, at(8, 15), at(9, 0), every=15)
    tl.stay(["zb", "zk", "zw"], HOME, at(8, 0), at(17, 0), every=20)
    tl.stay(["zr"], HOME, at(15, 40), at(17, 0), every=10)
    tl.ingest(session)
    got = texts(summary(session, sam))
    assert got.index("around 3:40 PM left School") < got.index("At Home from around 3:40 PM"), got
