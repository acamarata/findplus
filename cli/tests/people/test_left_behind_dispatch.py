"""alerts/dispatch_left_behind.py: one message per channel per episode, retry and the log."""

from __future__ import annotations

from findplus.alerts.dispatch_core import LeftBehindEvent, Rule
from findplus.alerts.dispatch_left_behind import left_behind_by_ids, match_left_behind
from findplus.alerts.group_event_rows import group_events_by_ids
from findplus.alerts.retry import _load_event
from findplus.api._delivery_render import batch_delivery_text_bodies
from findplus.db.models_people import LeftBehind

from ._helpers import Timeline, at, seed_person, seed_places
from .test_scenarios_left_behind import _bag_stays_at_school


def _rule(rid, channels, group_id=None, all_people=False, enabled=True):
    return Rule(rid, f"r{rid}", None, group_id, None, True, True, channels, 0, enabled, False,
                None, all_people)  # fmt: skip


def _event(group_id=1):
    return LeftBehindEvent(7, group_id, "Zaid", "zb", "Zaid Bag", "bag", 2, "School", at(15), None)


def test_each_channel_is_used_once_under_the_lowest_rule():
    rules = [
        _rule(3, ["telegram", "webhook"], all_people=True),
        _rule(1, ["telegram"], all_people=True),
        _rule(2, ["native"], group_id=1),
        _rule(4, ["whatsapp"], group_id=9),  # another person
        _rule(5, ["whatsapp"], all_people=True, enabled=False),
        _rule(6, ["telegram"], group_id=1),  # nothing new to add
    ]
    out = match_left_behind(rules, _event())
    assert [(r.id, r.channels) for r in out] == [(1, ["telegram"]), (2, ["native"]),
                                                 (3, ["webhook"])]  # fmt: skip


def test_retry_and_the_delivery_log_render_the_same_left_behind_text(session, pinned_tz):
    pinned_tz("UTC")
    seed_places(session)
    seed_person(session)
    _bag_stays_at_school(Timeline()).ingest(session)
    row = session.query(LeftBehind).filter_by(device_id="zb", state="left_behind").one()
    event = _load_event(session, "left_behind", row.id)
    assert event.place_name == "School" and event.role == "bag"
    text, body = batch_delivery_text_bodies(session, [("left_behind", row.id)])[
        ("left_behind", row.id)
    ]
    assert text.startswith("Zaid's bag looks left at School.")
    assert "Zaid was last seen near Home" in body
    assert left_behind_by_ids(session, []) == {}
    assert group_events_by_ids(session, []) == {}
    assert _load_event(session, "left_behind", 999) is None
