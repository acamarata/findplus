"""A fix is handed to the geofence once: fed clean, flagged, cleared is not fed again (r122 O8)."""

from __future__ import annotations

import pytest

import findplus.ingest as ing
from tests.quality._ingest import add_place, add_tracker, poll, verdict

DEV = "TAG-1"


@pytest.fixture
def fed(monkeypatch) -> list[int]:
    """Observation ids the geofence hook was asked to evaluate, in order."""
    seen: list[int] = []
    real = ing._geofence_evaluate

    def spy(session, lo, **kw):
        seen.append(lo.id)
        return real(session, lo, **kw)

    monkeypatch.setattr(ing, "_geofence_evaluate", spy)
    return seen


def test_a_clean_fix_is_stamped_when_it_is_fed(session, fed) -> None:
    add_tracker(session, DEV)
    add_place(session, "Home")
    poll(session, DEV, 0)
    row = verdict(session, DEV, 0)
    assert row.fed_at is not None and len(fed) == 1


def test_fed_then_flagged_then_cleared_is_not_fed_twice(session, fed) -> None:
    add_tracker(session, DEV)
    add_place(session, "Home")
    poll(session, DEV, 0)
    first = verdict(session, DEV, 0)
    first.suspect, first.reasons = True, "edge_stray"  # a later rescore flagged it
    session.flush()
    poll(session, DEV, 3, 5)  # this poll's rescore clears it again
    assert not verdict(session, DEV, 0).suspect
    assert fed.count(first.observation_id) == 1  # it was not fed a second time
    assert len(fed) == 2  # the new fix itself still went through


def test_a_fix_first_flagged_then_cleared_is_fed_once(session, fed) -> None:
    """The release path is intact: a never-fed fix still reaches the geofence."""
    add_tracker(session, DEV)
    add_place(session, "Home")
    poll(session, DEV, 0)
    poll(session, DEV, 3, 5)
    row = verdict(session, DEV, 3)
    fed.clear()
    row.suspect, row.reasons, row.fed_at = True, "edge_stray", None  # never fed
    session.flush()
    poll(session, DEV, 6, 8)
    assert fed.count(row.observation_id) == 1
    assert verdict(session, DEV, 3).fed_at is not None
