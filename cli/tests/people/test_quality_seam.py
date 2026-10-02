"""people/_quality.py: suspect sightings never place a person (spec § 6.3).

The quality package is built separately; these tests use a monkeypatched double
and never import findplus.quality themselves.
"""

from __future__ import annotations

from findplus.db.models import LocationObservation
from findplus.people import _quality

from ._helpers import (
    GRANDMA,
    HOME,
    Timeline,
    at,
    overnight,
    person_events,
    seed_person,
    seed_places,
)


def test_without_the_quality_package_nothing_is_suspect(session, monkeypatch):
    monkeypatch.setattr(_quality, "_suspect_ids", None)
    monkeypatch.setattr(_quality, "_is_suspect", None)
    assert _quality.suspect_ids(session, ["a"], at(0), at(1)) == set()
    assert _quality.is_suspect(session, 1) is False


def test_suspect_jump_never_moves_the_person(session, monkeypatch):
    """The owner's 4:17/4:18/4:19 case: one far sighting flagged suspect is skipped."""
    seed_places(session)
    zaid = seed_person(session)
    tl = Timeline()
    overnight(tl, ["zr", "zb", "zk", "zw"], end=at(16, 15))
    tl.ingest(session)
    flagged: set[int] = set()

    def suspect_ids(_s, _ids, _start, _end):
        return set(flagged)

    def is_suspect(_s, observation_id):
        return observation_id in flagged

    monkeypatch.setattr(_quality, "_suspect_ids", suspect_ids)
    monkeypatch.setattr(_quality, "_is_suspect", is_suspect)
    for when in (at(16, 17), at(16, 18)):
        Timeline().add("zr", HOME, when - (at(0, 1) - at(0)), acc=30).ingest(session)
    jump = Timeline().add("zr", GRANDMA, at(16, 19)).add("zb", GRANDMA, at(16, 19))
    jump.fixes.sort()
    # Flag the jump before it is ingested: the double answers by id once rows exist.
    original_ingest = jump.ingest

    def ingest_and_flag(session_):
        from sqlalchemy import event

        @event.listens_for(session_, "pending_to_persistent")
        def _flag(_sess, obj):
            if isinstance(obj, LocationObservation) and obj.observed_at == at(16, 19):
                flagged.add(obj.id)

        original_ingest(session_)
        event.remove(session_, "pending_to_persistent", _flag)

    ingest_and_flag(session)
    assert len(flagged) == 2
    Timeline().add("zr", HOME, at(16, 21)).add("zb", HOME, at(16, 21)).ingest(session)
    assert person_events(session, zaid.id) == []
