"""cli/src/findplus/groups/quorum.py — quorum_needed and evaluate_quorum."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from findplus.groups.quorum import QuorumInput, evaluate_quorum, quorum_needed

T0 = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)


def _q(**overrides) -> QuorumInput:
    base = {
        "group_id": 1,
        "quorum": "majority",
        "member_ids": ["a", "b", "c"],
        "stale_ids": [],
        "place_id": 1,
        "event_type": "ENTER",
        "window_minutes": 30,
        "member_events": [("a", 10, T0), ("b", 11, T0)],
    }
    base.update(overrides)
    return QuorumInput(**base)


def test_majority_fires_with_2_of_3() -> None:
    r = evaluate_quorum(_q())
    assert r.fire is True
    assert r.members_crossed == 2


def test_majority_all_crossed_confidence_high() -> None:
    r = evaluate_quorum(_q(member_events=[("a", 1, T0), ("b", 2, T0), ("c", 3, T0)]))
    assert r.confidence == "high"


def test_majority_partial_crossed_confidence_medium() -> None:
    r = evaluate_quorum(_q())
    assert r.confidence == "medium"


def test_majority_with_one_stale_fires() -> None:
    r = evaluate_quorum(_q(stale_ids=["c"]))
    assert r.fire is True
    assert r.confidence == "medium"


def test_all_quorum_never_fires_with_stale() -> None:
    r = evaluate_quorum(_q(quorum="all", stale_ids=["c"]))
    assert r.fire is False


def test_all_quorum_stale_full_cross_confidence_medium() -> None:
    r = evaluate_quorum(_q(quorum="all", stale_ids=["c"]))
    assert r.fire is False
    assert r.confidence == "medium"


def test_all_quorum_fires_when_no_stale() -> None:
    r = evaluate_quorum(_q(quorum="all", member_events=[("a", 1, T0), ("b", 2, T0), ("c", 3, T0)]))
    assert r.fire is True
    assert r.confidence == "high"


def test_any_fires_on_single_member() -> None:
    r = evaluate_quorum(_q(quorum="any", member_events=[("a", 1, T0)]))
    assert r.fire is True


def test_int_quorum_2_fires() -> None:
    r = evaluate_quorum(_q(quorum="2"))
    assert r.fire is True


def test_int_quorum_capped_at_considered() -> None:
    assert quorum_needed("5", 2) == 2


def test_duplicate_device_dedup() -> None:
    r = evaluate_quorum(
        _q(
            member_events=[
                ("a", 1, T0),
                ("a", 2, T0 + timedelta(minutes=5)),
            ]
        )
    )
    assert r.members_crossed == 1


def test_considered_zero_never_fires() -> None:
    r = evaluate_quorum(_q(member_ids=[], stale_ids=[], quorum="any", member_events=[]))
    assert r.fire is False


def test_naive_observed_at_raises() -> None:
    with pytest.raises(ValueError):
        evaluate_quorum(_q(member_events=[("a", 1, datetime(2026, 9, 19, 12, 0, 0))]))


def test_observed_at_is_max_of_crossed() -> None:
    t2 = T0 + timedelta(minutes=10)
    r = evaluate_quorum(_q(member_events=[("a", 1, T0), ("b", 2, t2)]))
    assert r.observed_at == t2


def test_unknown_quorum_raises() -> None:
    with pytest.raises(ValueError):
        evaluate_quorum(_q(quorum="weekly"))
