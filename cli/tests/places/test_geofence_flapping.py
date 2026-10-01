"""Noisy crowd-sourced fixes must not flap a geofence.

Fixes off by tens of metres are normal. A fix whose accuracy circle straddles
the edge is uncertain and decides nothing; leaving needs a fix clear of the
radius plus the larger of its accuracy and the exit margin, confirmed N times.
"""

from __future__ import annotations

from datetime import timedelta

from findplus.places.geofence import RECOMMENDED_MIN_RADIUS_METERS, evaluate_batch, exit_margin

from .test_geofence import T0, _fix, _inside_state, _outside_state, _place


def _run(state, place, points):
    """points: [(metres_north, accuracy)], one fix a minute, in order."""
    fixes = [
        _fix(m, acc, T0 + timedelta(minutes=i + 1), obs_id=i + 1)
        for i, (m, acc) in enumerate(points)
    ]
    return evaluate_batch(state, fixes, place)


def test_edge_jitter_inside_the_uncertain_band_never_alerts() -> None:
    # 80 m and 130 m on a 100 m place, 40 m accuracy: both straddle the edge.
    state, events = _run(_inside_state(T0), _place(), [(80, 40), (130, 40)] * 6)
    assert events == []
    assert state.state == "inside"


def test_alternating_clear_in_and_clear_out_never_alerts() -> None:
    # Clear inside, clear outside, repeat. Leaving needs 2 outside fixes in a
    # row, and every inside fix resets the streak, so nothing fires.
    state, events = _run(_inside_state(T0), _place(), [(40, 20), (200, 20)] * 8)
    assert events == []
    assert state.state == "inside"


def test_a_real_departure_alerts_once() -> None:
    state, events = _run(_inside_state(T0), _place(), [(200, 20)] * 5)
    assert [e.event_type for e in events] == ["EXIT"]
    assert state.state == "outside"


def test_a_departure_then_a_return_alerts_once_each() -> None:
    leave = [(220, 20)] * 3
    come_back = [(30, 20)] * 3
    state, events = _run(_inside_state(T0), _place(), leave + come_back + [(25, 20)] * 3)
    assert [e.event_type for e in events] == ["EXIT", "ENTER"]
    assert state.state == "inside"


def test_noise_while_away_does_not_re_alert() -> None:
    # Outside, then fixes wobbling near the edge: still no ENTER.
    state, events = _run(_outside_state(T0), _place(), [(90, 40), (120, 40), (140, 40)] * 4)
    assert events == []
    assert state.state == "outside"


def test_a_fix_less_accurate_than_the_radius_never_decides() -> None:
    state, events = _run(_inside_state(T0), _place(radius=50), [(500, 80)] * 6)
    assert events == []
    assert state.state == "inside"


def test_exit_margin_is_half_the_radius_with_a_floor() -> None:
    assert exit_margin(400) == 200
    assert exit_margin(100) == 50
    assert exit_margin(50) == 50
    assert RECOMMENDED_MIN_RADIUS_METERS == 100


def test_a_big_place_needs_a_bigger_margin_to_count_as_left() -> None:
    # 400 m place: outside needs more than 400 + max(30, 200) = 600 m.
    place = _place(radius=400)
    _, none = _run(_inside_state(T0), place, [(550, 30)] * 4)
    _, left = _run(_inside_state(T0), place, [(650, 30)] * 4)
    assert none == []
    assert [e.event_type for e in left] == ["EXIT"]
