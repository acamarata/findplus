"""Alert texts keep two same-named trackers apart (O11).

Every loader that builds a DeviceEvent swaps the plain label/name for
device_labels.unique_names, so the Telegram/webhook text names "Tag (dev1)" and
"Tag (dev2)" instead of "Tag" twice. A name that is unique stays as it was.
"""

from __future__ import annotations

from datetime import timedelta

from findplus.alerts.dispatch import load_pending_events
from findplus.alerts.dryrun import _device_events
from findplus.alerts.retry import _load_event
from findplus.db.models import PlaceEvent

from ._helpers import NOW, _seed_pending_place_event, _seed_place_and_device


def _twins(session) -> None:
    _seed_place_and_device(session, device_id="dev-aaaa")
    _seed_place_and_device(session, device_id="dev-bbbb")
    _seed_pending_place_event(session, 1, NOW, device_id="dev-aaaa")
    _seed_pending_place_event(session, 1, NOW + timedelta(minutes=1), device_id="dev-bbbb")


def test_pending_events_name_the_twins_apart(tmp_db, session) -> None:
    _twins(session)
    names = sorted(e.device_name for e in load_pending_events(session))
    assert names == ["Tag (aaaa)", "Tag (bbbb)"]


def test_a_unique_name_is_left_alone(tmp_db, session) -> None:
    _seed_place_and_device(session, device_id="dev-aaaa")
    _seed_pending_place_event(session, 1, NOW, device_id="dev-aaaa")
    assert [e.device_name for e in load_pending_events(session)] == ["Tag"]


def test_retry_reload_uses_the_same_names(tmp_db, session) -> None:
    _twins(session)
    ids = {r.device_id: r.id for r in session.query(PlaceEvent).all()}
    event = _load_event(session, "device", ids["dev-bbbb"])
    assert event.device_name == "Tag (bbbb)"


def test_dry_run_uses_the_same_names(tmp_db, session) -> None:
    _twins(session)
    names = sorted(e.device_name for e in _device_events(session, NOW - timedelta(hours=1)))
    assert names == ["Tag (aaaa)", "Tag (bbbb)"]
