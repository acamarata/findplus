"""The widget's headline device is the newest fix, not the first name.

E1 honesty round 2 F5: get_tracked_devices() returns stable NAME order and all
three widget views take devices.first, so the headline age, the freshness dot
and the large view's map snapshot belonged to whichever tag sorted first
alphabetically. widget.md pins "age of newest fix" and a snapshot "of the
newest fix".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from findplus.api._widget import _widget_devices
from findplus.db.session import session_scope
from findplus.ingest import ingest_observations, upsert_device
from findplus.state import track_devices
from tests.conftest import make_observation

NOW = datetime(2026, 9, 18, 13, 0, tzinfo=UTC)


def _seed(pairs: list[tuple[str, str, int]]) -> None:
    """(device_id, name, minutes_old) -> a tracked device with one fix that age."""
    with session_scope() as session:
        for device_id, name, minutes in pairs:
            upsert_device(session, device_id, name)
            ingest_observations(
                session,
                [
                    make_observation(
                        device_id=device_id,
                        device_name=name,
                        observed_at=NOW - timedelta(minutes=minutes),
                        lat=41.0 + minutes / 1e6,
                    )
                ],
                fetched_at=NOW,
            )
        track_devices(session, [p[0] for p in pairs], exclusive=True)


def _order(tmp_db) -> list[tuple[str, int]]:
    with session_scope() as session:
        rows = _widget_devices(session, NOW)
    return [(r["name"], r["age_minutes"]) for r in rows]


def test_the_freshest_device_comes_first_whatever_its_name(tmp_db) -> None:
    _seed([("A", "Alice bag", 3 * 24 * 60), ("Z", "Zoe tag", 2)])

    order = _order(tmp_db)

    assert order[0][0] == "Zoe tag", f"the widget would headline {order[0][0]}"
    assert order[0][1] == 2
    assert [n for n, _ in order] == ["Zoe tag", "Alice bag"]


def test_renaming_a_tag_does_not_change_the_headline(tmp_db) -> None:
    """The bug's tell: the order used to flip when the names swapped."""
    _seed([("A", "Zebra bag", 3 * 24 * 60), ("Z", "Aaron tag", 2)])

    assert _order(tmp_db)[0][0] == "Aaron tag"


def test_ages_come_back_ascending(tmp_db) -> None:
    _seed([("A", "a", 500), ("B", "b", 5), ("C", "c", 50)])

    ages = [age for _, age in _order(tmp_db)]
    assert ages == sorted(ages)
