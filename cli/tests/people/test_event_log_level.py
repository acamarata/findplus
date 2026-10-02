"""A person's arrivals and departures are never an INFO log line (no presence log)."""

from __future__ import annotations

from structlog.testing import capture_logs

from ._helpers import HOME, SCHOOL, Timeline, at, overnight, seed_person, seed_places


def test_person_place_events_log_at_debug_only(session):
    seed_places(session)
    seed_person(session)
    tl = Timeline()
    overnight(tl, ["zr", "zb"], end=at(7, 40))
    tl.walk(["zr", "zb"], HOME, SCHOOL, at(7, 40), at(8, 10), every=5)
    tl.stay(["zr", "zb"], SCHOOL, at(8, 30), at(15, 0), every=20)
    with capture_logs() as logs:
        tl.ingest(session)
    person = [e for e in logs if e["event"] == "person_place_event"]
    assert person, "the scenario must produce person events"
    assert {e["log_level"] for e in person} == {"debug"}
    assert not [e for e in person if "latitude" in e or "name" in e]
