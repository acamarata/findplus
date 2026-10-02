"""Person alert times: same day reads "7:31 AM", another day keeps its date (uat116 #14)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from findplus.alerts.dispatch_core import GroupEvent, LeftBehindEvent
from findplus.alerts.render_person import render_person_message

SENT = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


def _event(observed: datetime) -> GroupEvent:
    return GroupEvent(
        group_place_event_id=1, group_id=1, group_name="Sam", place_id=1, place_name="Home",
        event_type="EXIT", observed_at=observed, confidence="high", note="", members_crossed=1,
        members_considered=1, members_stale=0, basis="person", group_kind="person",
        lead_device_id="zb", lead_name="Sam Bag", fetched_at=observed + timedelta(minutes=12),
    )  # fmt: skip


def test_same_day_times_have_no_date_or_zone(pinned_tz):
    pinned_tz("UTC")
    lines = render_person_message(_event(SENT.replace(hour=7, minute=31)), SENT).splitlines()
    assert lines[0] == "Sam left Home at 7:31 AM"
    assert lines[1] == "Seen by Sam Bag · reported 7:43 AM · 12 min late"


def test_an_event_from_another_day_keeps_its_date(pinned_tz):
    pinned_tz("UTC")
    first = render_person_message(_event(SENT - timedelta(days=1)), SENT).splitlines()[0]
    assert first == "Sam left Home at Oct 1, 12:00 PM UTC"


def test_left_behind_same_day_time(pinned_tz):
    pinned_tz("UTC")
    seen = SENT.replace(hour=9, minute=5)
    event = LeftBehindEvent(7, 1, "Sam", "zb", "Sam Bag", "bag", 2, "School", seen, seen)
    first = render_person_message(event, SENT).splitlines()[0]
    assert first == "Sam's bag looks left at School. Last seen there at 9:05 AM."
