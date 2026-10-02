"""sibling_disagree holds a fix for its own next fix instead of condemning it.

Review 2026-10-02 #3: a child who takes only the bag (shoes and watch stay
home) left the bag's first far fix suspect, so the School ENTER fired one bag
report late (48 minutes in the review's run). V5 (a still bag that suddenly
reports 3 km away and comes straight back) must stay caught, and a bag left
behind (it keeps reporting the same place) is never flagged.
"""

from __future__ import annotations

from datetime import timedelta

from findplus.groups.repo import create_group
from findplus.ingest import release_held_fixes
from tests.quality._ingest import add_place, add_tracker, at, events, poll, verdict

BAG, SHOES, WATCH = "BAG", "SHOES", "WATCH"
SCHOOL_M = 3000


def _world(session) -> None:
    for dev in (BAG, SHOES, WATCH):
        add_tracker(session, dev)
    create_group(session, name="Kid", kind="person", member_ids=[BAG, SHOES, WATCH])
    add_place(session, "Home")
    add_place(session, "School", SCHOOL_M)
    session.flush()


def _all_home_until(session, minutes: int) -> None:
    for m in range(0, minutes + 1, 10):
        poll(session, BAG, m, 5)
        poll(session, SHOES, m + 2, -5)
        poll(session, WATCH, m + 4, 8, 3)


def test_only_the_bag_leaves_and_school_enters_on_its_first_fix(session) -> None:
    _world(session)
    _all_home_until(session, 50)
    poll(session, SHOES, 57, -4)
    poll(session, WATCH, 58, 6)
    poll(session, BAG, 60, SCHOOL_M)  # siblings agree at home: held, not condemned
    assert events(session, "School", device=BAG) == []
    poll(session, BAG, 63, SCHOOL_M + 20)  # the bag's own next fix agrees
    assert [e.observed_at for e in events(session, "School", device=BAG)] == [at(60)]
    assert not verdict(session, BAG, 60).suspect


def test_only_the_bag_leaves_and_nothing_follows_the_clock_releases_it(session) -> None:
    _world(session)
    _all_home_until(session, 50)
    poll(session, SHOES, 57, -4)
    poll(session, WATCH, 58, 6)
    poll(session, BAG, 60, SCHOOL_M)
    release_held_fixes(session, now=at(60) + timedelta(minutes=13))
    assert [e.observed_at for e in events(session, "School", device=BAG)] == [at(60)]


def test_v5_a_still_bag_that_jumps_and_comes_back_never_enters(session) -> None:
    _world(session)
    _all_home_until(session, 50)
    poll(session, SHOES, 57, -4)
    poll(session, WATCH, 58, 6)
    poll(session, BAG, 60, SCHOOL_M)
    poll(session, BAG, 63, 10)  # straight back home
    assert verdict(session, BAG, 60).suspect
    assert events(session, "School") == []


def test_a_bag_left_behind_keeps_reporting_and_is_never_flagged(session) -> None:
    _world(session)
    _all_home_until(session, 30)
    for m in range(40, 100, 10):  # the child leaves with shoes and watch; the bag stays
        poll(session, SHOES, m, SCHOOL_M)
        poll(session, WATCH, m + 1, SCHOOL_M + 10)
        poll(session, BAG, m + 2, 5)
    assert not any(verdict(session, BAG, m + 2).suspect for m in range(40, 100, 10))
