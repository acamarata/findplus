"""A fix flagged at ingest and cleared later reaches the geofence, in observed order.

Review 2026-10-02 #2 and #5: only `jump_unconfirmed` was ever released, so a
fast arrival flagged `edge_stray` ENTERed one fix late (or never), and a held
fix waited for some later ingest that might not come.
"""

from __future__ import annotations

from datetime import timedelta

from findplus.ingest import release_held_fixes
from tests.quality._ingest import add_place, add_tracker, at, events, poll, verdict

DEV = "TAG-1"
TRAIN_STEP_M = 80 * 180  # a fast train: 80 m/s for three minutes


def test_a_fast_train_arrival_enters_at_the_first_fix_inside(session) -> None:
    add_tracker(session, DEV)
    add_place(session, "Station", 3 * TRAIN_STEP_M)
    for k in range(3):
        poll(session, DEV, 3 * k, k * TRAIN_STEP_M)
    poll(session, DEV, 9, 3 * TRAIN_STEP_M)  # arrives: too fast from the last fix, held
    assert events(session, "Station") == []
    poll(session, DEV, 12, 3 * TRAIN_STEP_M + 30)  # still there
    assert [e.observed_at for e in events(session, "Station")] == [at(9)]
    assert not verdict(session, DEV, 9).suspect


def test_a_fast_train_departure_exits_on_the_second_fix_outside(session) -> None:
    add_tracker(session, DEV)
    add_place(session, "Home")
    for k in range(4):
        poll(session, DEV, 3 * k, 5 * k)
    for k in range(1, 4):
        poll(session, DEV, 9 + 3 * k, k * TRAIN_STEP_M)
    # Exit needs two fixes outside: the first one (12:00) and the second (15:00).
    assert [e.observed_at for e in events(session, "Home", "EXIT")] == [at(15)]


def test_a_plane_arrival_enters_on_the_first_fix(session) -> None:
    add_tracker(session, DEV)
    add_place(session, "Away", 600_000, radius=500)
    for k in range(4):
        poll(session, DEV, 3 * k)
    poll(session, DEV, 160, 600_000)  # 600 km in about 2.5 hours
    assert [e.observed_at for e in events(session, "Away")] == [at(160)]


def test_a_held_fix_is_released_by_the_clock_with_its_own_time(session) -> None:
    add_tracker(session, DEV)
    add_place(session, "Far", 2500)
    poll(session, DEV, 0)
    poll(session, DEV, 3, 2500)
    assert verdict(session, DEV, 3).suspect and events(session, "Far") == []
    fetched = at(3) + timedelta(seconds=20)
    assert release_held_fixes(session, now=fetched + timedelta(minutes=5)) == 0
    assert events(session, "Far") == []
    assert release_held_fixes(session, now=fetched + timedelta(minutes=13)) == 1
    assert [e.observed_at for e in events(session, "Far")] == [at(3)]
    assert release_held_fixes(session, now=fetched + timedelta(minutes=20)) == 0
    assert len(events(session, "Far")) == 1


def test_a_held_fix_whose_next_fix_comes_much_later_is_still_released(session) -> None:
    add_tracker(session, DEV)
    add_place(session, "Far", 2500)
    poll(session, DEV, 0)
    poll(session, DEV, 3, 2500)
    poll(session, DEV, 5 * 60, 2510)  # five hours later, same far place
    assert not verdict(session, DEV, 3).suspect
    assert [e.observed_at for e in events(session, "Far")] == [at(3)]
