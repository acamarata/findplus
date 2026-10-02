"""DigestScheduler: a fake clock, a fake channel, no network (spec § 7.2)."""

from __future__ import annotations

import threading
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest

from findplus import honesty
from findplus.db.models_people import DigestRun
from findplus.db.session import session_scope
from findplus.people import digest_prefs
from findplus.service.digest import STALE_CLAIM, DigestScheduler

from ._digest_helpers import FakeChannel, connect_telegram, seed_school_day
from ._helpers import at

UTC_TZ = ZoneInfo("UTC")


def make(fake: FakeChannel, **kw) -> DigestScheduler:
    return DigestScheduler(tz=kw.pop("tz", UTC_TZ), sender=fake, **kw)


def turn_on(**patch) -> None:
    with session_scope() as s:
        digest_prefs.save(s, {"enabled": True, **patch})


def runs() -> list[tuple[str, str, str]]:
    with session_scope() as s:
        rows = s.query(DigestRun).order_by(DigestRun.id).all()
        return [(r.local_date, r.target, r.status) for r in rows]


@pytest.fixture
def world(tmp_db):
    (pid,) = seed_school_day()
    connect_telegram(("42",))
    return pid


def test_off_by_default_sends_nothing(world):
    fake = FakeChannel()
    assert make(fake).tick(at(21, 0)) == [] and fake.sent == [] and runs() == []


def test_not_due_before_the_set_time_then_sent_once(world):
    turn_on()
    fake = FakeChannel()
    sched = make(fake)
    assert sched.tick(at(19, 59)) == [] and fake.sent == []
    out = sched.tick(at(20, 0))
    assert [(o.status, o.target) for o in out] == [("sent", "42")]
    assert len(fake.sent) == 1 and runs() == [("2026-09-21", "42", "sent")]
    text = fake.sent[0][0]
    assert text.startswith("Zaid's day, Mon Sep 21") and "- 7:40 AM left Home" in text
    assert text.count(honesty.ALERTS_LATENCY) == 1
    for minute in (1, 2, 30):  # later ticks the same evening never resend
        assert sched.tick(at(20, minute)) == []
    assert len(fake.sent) == 1


def test_a_restart_never_double_sends(world):
    turn_on()
    fake = FakeChannel()
    make(fake).tick(at(20, 5))
    again = make(fake)  # a new process, same database
    assert again.tick(at(20, 6)) == [] and again.tick(at(23, 59)) == []
    assert len(fake.sent) == 1 and len(runs()) == 1


def test_next_day_sends_again_and_the_time_is_the_local_one(world):
    turn_on(time="20:00")
    fake = FakeChannel()
    sched = make(fake, tz=ZoneInfo("America/New_York"))  # 20:00 EDT is 00:00 UTC
    assert sched.tick(at(23, 59)) == []  # 19:59 in New York
    sched.tick(at(0, 0, day=1))
    assert [r[0] for r in runs()] == ["2026-09-21"]
    sched.tick(at(0, 0, day=2))
    assert [r[0] for r in runs()] == ["2026-09-21", "2026-09-22"]
    assert len(fake.sent) == 1  # the 22nd had nothing tracked: skipped, not sent
    assert runs()[1][2] == "skipped"


def test_each_chat_target_is_its_own_row(world):
    connect_telegram(("42", "@family_chat"))
    turn_on()
    fake = FakeChannel()
    out = make(fake).tick(at(20, 0))
    assert [o.target for o in out] == ["42", "@family_chat"]
    assert [r[1] for r in runs()] == ["42", "@family_chat"]
    make(fake).tick(at(20, 1))
    assert len(fake.sent) == 2


def test_held_while_locked_then_sent_after_unlock(world):
    turn_on()
    fake, locked = FakeChannel(), {"on": True}
    sched = make(fake, is_locked=lambda: locked["on"])
    out = sched.tick(at(20, 0))
    assert [o.status for o in out] == ["held"] and fake.sent == [] and runs() == []
    locked["on"] = False
    out = sched.tick(at(22, 30))
    assert [o.status for o in out] == ["sent"] and len(fake.sent) == 1


def test_a_failed_send_is_retried_once_the_next_minute(world):
    turn_on()
    fake = FakeChannel(fail=1)
    sched = make(fake)
    assert [o.status for o in sched.tick(at(20, 0))] == ["retry"]
    assert sched.tick(at(20, 0) + timedelta(seconds=20)) == []  # too soon
    assert [o.status for o in sched.tick(at(20, 1))] == ["sent"]
    assert len(fake.sent) == 2 and runs() == [("2026-09-21", "42", "sent")]
    assert sched.tick(at(20, 2)) == []


def test_two_failures_are_final_and_logged_not_retried_again(world):
    turn_on()
    fake = FakeChannel(fail=5)
    sched = make(fake)
    sched.tick(at(20, 0))
    out = sched.tick(at(20, 1))
    assert [o.status for o in out] == ["failed"] and "HTTP 500" in out[0].error
    assert sched.tick(at(20, 2)) == [] and sched.tick(at(21, 0)) == []
    assert len(fake.sent) == 2 and runs() == [("2026-09-21", "42", "failed")]


def test_a_day_with_nothing_tracked_sends_nothing(world):
    turn_on()
    fake = FakeChannel()
    sched = make(fake)
    out = sched.tick(at(20, 0, day=3))  # nothing was ingested on the 24th
    assert [o.status for o in out] == ["skipped"] and fake.sent == []
    assert sched.tick(at(20, 5, day=3)) == []  # and it does not recompute every minute


def test_always_send_says_nothing_was_tracked(world):
    turn_on(always_send=True)
    fake = FakeChannel()
    make(fake).tick(at(20, 0, day=3))
    assert len(fake.sent) == 1 and "No sightings for Zaid on this day." in fake.sent[0][0]


def test_no_connected_chat_holds_quietly(tmp_db):
    seed_school_day()
    turn_on()
    fake = FakeChannel()
    out = make(fake).tick(at(20, 0))
    assert [o.status for o in out] == ["no_channel"] and fake.sent == [] and runs() == []


def test_only_the_chosen_people_get_a_summary(world):
    with session_scope() as s:
        from ._helpers import seed_person

        other = seed_person(s, "Amirah", {"am": "Amirah"})
        other_id = other.id
    turn_on(people=[other_id])
    fake = FakeChannel()
    out = make(fake).tick(at(20, 0))
    assert [(o.person_id, o.status) for o in out] == [(other_id, "skipped")]
    assert fake.sent == []  # Amirah had nothing tracked; Zaid was not chosen


def test_a_crash_mid_send_is_never_resent(world):
    turn_on()
    with session_scope() as s:
        s.add(DigestRun(group_id=world, local_date="2026-09-21", channel="telegram", target="42",
                        status="sending", sent_at=at(20, 0)))  # fmt: skip
    fake = FakeChannel()
    sched = make(fake)
    assert sched.tick(at(20, 3)) == [] and fake.sent == []
    sched.tick(at(20, 0) + STALE_CLAIM + timedelta(minutes=1))
    assert runs() == [("2026-09-21", "42", "failed")] and fake.sent == []


def test_the_loop_survives_a_bad_tick_and_stops(world, monkeypatch):
    sched = DigestScheduler(tz=UTC_TZ, interval=0.01)
    calls = {"n": 0}

    def flaky(now=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        if calls["n"] >= 3:
            sched.stop()
        return []

    monkeypatch.setattr(sched, "tick", flaky)
    thread = threading.Thread(target=sched.run_forever, daemon=True)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive() and calls["n"] >= 3
