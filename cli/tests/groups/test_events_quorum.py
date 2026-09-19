"""groups/events.py -- quorum evaluation, unit-level (evaluate_group_events directly).

Split out of test_events.py (PRI rule 7, <=300 lines/file); the ingest-hook
integration tests (which exercise ingest_observations end to end) stayed in
test_events.py. Shared seed/builder helpers live in _helpers.py.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from findplus.db.models import GroupPlaceEvent
from findplus.groups.events import evaluate_group_events

from ._helpers import T0, _add_fix, _add_place_event, _seed_group, _Settings


def test_majority_fires_on_2_of_3(session):
    _group, place = _seed_group(session)
    pe_a = _add_place_event(session, place, "a", "ENTER", T0)
    _add_place_event(session, place, "b", "ENTER", T0 + timedelta(minutes=1))
    _add_fix(session, "c", T0)  # reporting, but never crossed

    rows = evaluate_group_events(session, pe_a, _Settings(), now=T0 + timedelta(minutes=1))

    assert len(rows) == 1
    assert rows[0].members_crossed == 2
    assert rows[0].members_considered == 3
    assert rows[0].event_type == "ENTER"
    saved = session.scalar(select(GroupPlaceEvent))
    assert saved is not None and saved.id == rows[0].id


def test_third_member_later_in_same_window_no_second_row(session):
    _group, place = _seed_group(session)
    pe_a = _add_place_event(session, place, "a", "ENTER", T0)
    _add_place_event(session, place, "b", "ENTER", T0 + timedelta(minutes=1))
    _add_fix(session, "c", T0)
    evaluate_group_events(session, pe_a, _Settings(), now=T0 + timedelta(minutes=1))

    pe_c = _add_place_event(session, place, "c", "ENTER", T0 + timedelta(minutes=5))
    rows = evaluate_group_events(session, pe_c, _Settings(), now=T0 + timedelta(minutes=5))

    assert rows == []
    assert len(list(session.scalars(select(GroupPlaceEvent)))) == 1


def test_stale_member_excluded_from_considered(session):
    _group, place = _seed_group(session)
    pe_a = _add_place_event(session, place, "a", "ENTER", T0)
    _add_place_event(session, place, "b", "ENTER", T0 + timedelta(minutes=1))
    # "c" last reported 2 hours before `now` -- stale under the 60-minute default.
    _add_fix(session, "c", T0 - timedelta(hours=2))

    rows = evaluate_group_events(session, pe_a, _Settings(), now=T0 + timedelta(minutes=1))

    assert len(rows) == 1
    assert rows[0].members_considered == 2
    assert rows[0].members_crossed == 2
    assert rows[0].members_stale == 1


def test_all_members_stale_no_row(session):
    _group, place = _seed_group(session)
    pe_a = _add_place_event(session, place, "a", "ENTER", T0)
    now = T0 + timedelta(hours=3)  # everyone's fix (including a's) is now stale

    rows = evaluate_group_events(session, pe_a, _Settings(), now=now)

    assert rows == []
    assert session.scalar(select(GroupPlaceEvent)) is None


def test_any_quorum_fires_on_first_member(session):
    group, place = _seed_group(session, quorum="any")
    pe_a = _add_place_event(session, place, "a", "ENTER", T0)
    _add_fix(session, "b", T0)
    _add_fix(session, "c", T0)

    rows = evaluate_group_events(session, pe_a, _Settings(), now=T0)

    assert len(rows) == 1
    assert rows[0].group_id == group.id
    assert rows[0].members_crossed == 1
