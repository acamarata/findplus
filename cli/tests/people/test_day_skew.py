"""The day summary leaves out clock-skewed and flagged sightings, like the engine (r122 O6).

A sighting that claims a time later than its first fetch + 5 min is from a
reporter with a fast clock. The person engine already ignores it; the day
summary must not draw a stay or a story line from it either.
"""

from __future__ import annotations

from findplus.db.models import LocationObservation
from findplus.db.models_people import ObservationQuality

from ._day_helpers import ALL, summary, texts
from ._helpers import GRANDMA, HOME, Timeline, at, seed_person, seed_places


def _quiet_home_day(session):
    seed_places(session)
    sam = seed_person(session)
    Timeline().stay(ALL, HOME, at(0, 0), at(17, 0), every=30).ingest(session)
    return sam


def _stray(
    session, device: str, minutes: list[int], fetched_at, suspect: bool = False
) -> list[int]:
    """Direct rows at Grandma's (no ingest, so no quality row unless `suspect`)."""
    ids = []
    for m in minutes:
        row = LocationObservation(
            device_id=device,
            device_name=device,
            latitude_e7=round(GRANDMA[0] * 1e7),
            longitude_e7=round(GRANDMA[1] * 1e7),
            accuracy_meters=30.0,
            observed_at=at(10, m),
            first_fetched_at=fetched_at,
            last_fetched_at=fetched_at,
            source="crowdsourced",
        )
        session.add(row)
        session.flush()
        ids.append(row.id)
        if suspect:
            session.add(
                ObservationQuality(
                    observation_id=row.id,
                    score=0.1,
                    suspect=True,
                    reasons="aba_teleport",
                    algo_version=1,
                    computed_at=fetched_at,
                )
            )
    session.flush()
    return ids


def _visit(session, lag_minutes: int):
    """Sam at Home until 9:00, then every tracker at Grandma's 10:00-12:00."""
    seed_places(session)
    sam = seed_person(session)
    Timeline().stay(ALL, HOME, at(0, 0), at(9, 0), every=30).ingest(session)
    Timeline().stay(ALL, GRANDMA, at(10, 0), at(12, 0), every=10).ingest(
        session, lag_minutes=lag_minutes
    )
    return sam


def test_a_visit_from_a_fast_clock_reporter_draws_no_stay_or_story_line(session):
    sam = _visit(session, lag_minutes=-400)  # fetched six hours before they claim to be seen
    payload = summary(session, sam)
    assert not any("Grandma" in t for t in texts(payload))
    assert all(t["last_at"] < "2026-09-21T09:30:00Z" for t in payload["trackers"])
    assert payload["suspect_count"] == 0  # silently left out, like the engine does


def test_the_same_visit_with_an_honest_clock_is_drawn(session):
    """The control: fetched when they were seen, the visit is real and shows up."""
    sam = _visit(session, lag_minutes=5)
    payload = summary(session, sam)
    assert any("Grandma" in t for t in texts(payload))
    assert any(t["last_at"] > "2026-09-21T11:00:00Z" for t in payload["trackers"])


def test_flagged_sightings_stay_out_of_the_story(session):
    sam = _quiet_home_day(session)
    before = summary(session, sam)
    _stray(session, "zr", [0, 10, 20, 30], at(10, 31), suspect=True)
    after = summary(session, sam)
    assert texts(after) == texts(before)
    assert after["suspect_count"] == before["suspect_count"] + 4
