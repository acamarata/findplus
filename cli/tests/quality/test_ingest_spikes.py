"""A one-fix spike never fires an ENTER, at any cadence Find Hub really uses."""

from __future__ import annotations

import pytest

from tests.quality._ingest import add_place, add_tracker, at, events, poll, verdict

DEV = "TAG-1"


@pytest.mark.parametrize(
    ("far_m", "gap_min"),
    [(2500, 1), (1500, 3), (1000, 3), (2500, 5), (4000, 10), (600, 1), (400, 1)],
)
def test_a_spike_into_a_place_and_back_never_enters_it(session, far_m, gap_min) -> None:
    add_tracker(session, DEV)
    add_place(session, "Home")
    add_place(session, "Far", far_m, radius=150)
    poll(session, DEV, 0)
    poll(session, DEV, gap_min, far_m, acc=40)
    assert events(session, "Far") == []  # held: the next fix decides
    poll(session, DEV, 2 * gap_min, 60)
    assert verdict(session, DEV, gap_min).suspect
    assert "aba_teleport" in verdict(session, DEV, gap_min).reasons
    assert events(session, "Far") == []
    assert events(session, "Home", "EXIT") == []


def test_a_real_arrival_at_three_minute_cadence_enters_at_the_right_time(session) -> None:
    add_tracker(session, DEV)
    add_place(session, "Home")
    add_place(session, "Far", 1500, radius=150)
    poll(session, DEV, 0)
    poll(session, DEV, 3, 1500)
    assert events(session, "Far") == []
    poll(session, DEV, 6, 1520)  # still there: the arrival was real
    enters = events(session, "Far")
    assert [e.observed_at for e in enters] == [at(3)]
