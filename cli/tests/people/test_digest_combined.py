"""One family message instead of one per person (uat116 #13)."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from findplus import honesty
from findplus.db.models_people import DigestRun
from findplus.db.session import session_scope
from findplus.people import digest_prefs
from findplus.people.day_render import _line, heading
from findplus.service.digest import DigestScheduler

from ._digest_helpers import FakeChannel, connect_telegram, seed_school_day
from ._helpers import HOME, Timeline, at, seed_person

UTC_TZ = ZoneInfo("UTC")


@pytest.fixture
def family(tmp_db):
    seed_school_day()
    with session_scope() as s:
        seed_person(s, "Whiskers", {"cat": "Whiskers Collar"}, kind="pet")
        Timeline().stay(["cat"], HOME, at(6, 0), at(18, 0), every=60).ingest(s)
    connect_telegram(("42", "43"))


def _on(**patch):
    with session_scope() as s:
        digest_prefs.save(s, {"enabled": True, **patch})


def test_combined_is_the_default_and_sends_one_message_per_chat(family):
    _on()
    fake = FakeChannel()
    DigestScheduler(tz=UTC_TZ, sender=fake).tick(at(20, 0))
    assert sorted(chat for _, _, chat in fake.sent) == ["42", "43"]
    text = fake.sent[0][0]
    assert text.startswith("Everyone's day, Mon Sep 21")
    assert "\nSam\n" in text and "\nWhiskers\n" in text
    assert text.count(honesty.ALERTS_LATENCY) == 1
    assert text.count(honesty.TRIPS_APPROXIMATE) == 1
    with session_scope() as s:
        assert s.query(DigestRun).filter_by(status="sent").count() == 4  # 2 people x 2 chats
    assert DigestScheduler(tz=UTC_TZ, sender=fake).tick(at(20, 5)) == []
    assert len(fake.sent) == 2


def test_one_message_per_person_when_combined_is_off(family):
    _on(combined=False)
    fake = FakeChannel()
    DigestScheduler(tz=UTC_TZ, sender=fake).tick(at(20, 0))
    assert len(fake.sent) == 4
    assert any(t.startswith("Whiskers' day, Mon Sep 21") for t, _, _ in fake.sent)


def test_possessive_and_no_double_brackets():
    payload = {"date": "2026-09-21", "person": {"name": "Whiskers"}}
    assert heading(payload) == "Whiskers' day, Mon Sep 21"
    line = {"text": "Still at School (seen 7:40 AM)", "via": "bag, bike and 1 more"}
    assert _line(line) == "Still at School (seen 7:40 AM; bag, bike and 1 more)"
    assert _line({"text": "7:40 AM left Home", "via": "shoes"}) == "7:40 AM left Home (shoes)"
