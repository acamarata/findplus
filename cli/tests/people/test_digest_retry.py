"""A day skipped as "nothing tracked" is looked at again; a sent day never goes twice (r122 O14)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from findplus.db.session import session_scope
from findplus.service.digest import SKIP_RECHECK

from ._digest_helpers import FakeChannel, connect_telegram, seed_school_day
from ._helpers import HOME, Timeline, at
from .test_digest_scheduler import make, runs, turn_on

EMPTY = 3  # the 24th: nothing ingested by seed_school_day


@pytest.fixture
def world(tmp_db):
    seed_school_day()
    connect_telegram(("42",))


def _first_sighting(minute: int, day: int = EMPTY) -> None:
    """Sam's shoes report from Home for the first time that day, `minute` after 20:00."""
    with session_scope() as s:
        Timeline().stay(
            ["zr", "zb"], HOME, at(20, minute, day), at(20, minute + 10, day), every=5
        ).ingest(s)


def test_a_day_skipped_at_send_time_is_sent_once_its_first_sighting_arrives(world):
    turn_on()
    fake = FakeChannel()
    sched = make(fake)
    assert [o.status for o in sched.tick(at(20, 0, EMPTY))] == ["skipped"]
    _first_sighting(5)
    assert sched.tick(at(20, 6, EMPTY)) == []  # too soon to look again
    out = sched.tick(at(20, 0, EMPTY) + SKIP_RECHECK)
    assert [(o.status, o.target) for o in out] == [("sent", "42")]
    assert len(fake.sent) == 1 and "Sam" in fake.sent[0][0]
    assert runs()[-1] == ("2026-09-24", "42", "sent")
    for minute in (16, 40):  # a sent day is never sent again, nor re-read
        assert sched.tick(at(20, minute, EMPTY)) == []
    assert sched.tick(at(8, 0, EMPTY + 1)) == [] and len(fake.sent) == 1


def test_a_day_that_stays_empty_is_rechecked_without_spamming(world):
    turn_on()
    fake = FakeChannel()
    sched = make(fake)
    sched.tick(at(20, 0, EMPTY))
    assert [o.status for o in sched.tick(at(20, 0, EMPTY) + SKIP_RECHECK)] == ["skipped"]
    assert fake.sent == [] and runs() == [("2026-09-24", "42", "skipped")]  # one row, updated


def test_the_next_morning_still_picks_up_a_late_first_sighting(world):
    turn_on()
    fake = FakeChannel()
    sched = make(fake)
    sched.tick(at(20, 0, EMPTY))
    _first_sighting(40)  # arrives after the evening ticks stopped looking
    out = sched.tick(at(8, 0, EMPTY + 1))
    assert [o.status for o in out] == ["sent"] and len(fake.sent) == 1
    assert ("2026-09-24", "42", "sent") in runs()
    # the new day is not sent early by the morning pass
    assert all(r[0] == "2026-09-24" for r in runs())


def test_after_the_morning_window_a_skipped_day_stays_skipped(world):
    turn_on()
    fake = FakeChannel()
    sched = make(fake)
    sched.tick(at(20, 0, EMPTY))
    _first_sighting(40)
    assert [o for o in sched.tick(at(13, 0, EMPTY + 1)) if o.person_id] == []
    assert fake.sent == [] and runs() == [("2026-09-24", "42", "skipped")]


def test_the_retry_goes_out_while_the_app_is_locked(world):
    from findplus.appsettings import save_pin
    from findplus.security import hash_pin

    turn_on()
    sched = make(fake := FakeChannel())
    sched.tick(at(20, 0, EMPTY))
    _first_sighting(5)
    with session_scope() as s:
        salt, digest = hash_pin("246810")
        save_pin(s, salt, digest)
    out = sched.tick(at(20, 0, EMPTY) + SKIP_RECHECK)
    assert [o.status for o in out] == ["sent"] and len(fake.sent) == 1


def test_a_failed_retry_send_is_retried_like_any_first_send(world):
    turn_on()
    sched = make(fake := FakeChannel(fail=1))
    sched.tick(at(20, 0, EMPTY))
    _first_sighting(5)
    t = at(20, 0, EMPTY) + SKIP_RECHECK
    assert [o.status for o in sched.tick(t)] == ["retry"]
    assert [o.status for o in sched.tick(t + timedelta(minutes=1))] == ["sent"]
    assert len(fake.sent) == 2
