"""Shared helpers for the geofence+alerts end-to-end suite.

Purpose    : One definition of the fix-feeding/dispatch/message-assertion
             helpers shared by test_geofence_alerts_e2e.py (device leave/
             return) and test_geofence_alerts_e2e_group.py (a group rule),
             split out so each test module stays under the PRI 300-line cap.
Inputs     : A SQLAlchemy `session` (the tmp_db-backed fixture in
             cli/tests/conftest.py) and pytest's `register_provider` fixture.
Outputs    : n/a (test-only builders and assertion helpers).
Constraints: test-only; never imported by cli/src. Fixes are anchored to a
             `base = datetime.now(UTC)` the caller captures once per test, not
             a fixed past date: the ingest-time group-quorum hook
             (findplus.groups.events.evaluate_group_events) reads staleness
             off the REAL wall clock when poll_device calls it, so a fixed
             historical anchor would read every member -- including the one
             that just crossed -- as stale (no fix within presence_window_
             minutes of "real now") and a group rule would silently never
             fire. Alert dispatch itself is triggered explicitly (never
             through poll_device's own automatic call, which uses the real
             wall clock) with a fixed `now`, so the rendered message's
             "Observed <local time>" stays deterministic under pinned_tz
             (R-P2-31).
"""

from __future__ import annotations

import re
import types
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from findplus.alerts import dispatch
from findplus.alerts.channels_field import format_channels
from findplus.db.models import Place
from findplus.db.models_alerts import AlertRule
from findplus.honesty import ALERTS_LATENCY
from findplus.ingest import upsert_device
from findplus.poller import poll_device
from tests.poller_fakes import FakeProvider

ZONE = "America/New_York"
PLACE_NAME = "Home"
#: ~499m from (0,0): unambiguously past radius(100) + max(accuracy, 50).
OUTSIDE_LAT = 0.004492
#: ~120m from (0,0): past the radius, but paired with accuracy=150 (> the
#: radius) so classify() reads it as low-confidence/indeterminate regardless.
EDGE_LAT = 0.001078

_ALERTS_ON = types.SimpleNamespace(alerts_enabled=True)


def local_time(base: datetime, minutes_ago: float) -> str:
    """The exact local time render_message() prints for this offset (R-P2-31,
    updated by UAT7 N06 to the delivery log row's own "Sep 26, 2:12 PM EDT"
    format -- see dispatch_core._fmt_local_time())."""
    from findplus.alerts.dispatch_core import _fmt_local_time

    return _fmt_local_time((base - timedelta(minutes=minutes_ago)).astimezone(ZoneInfo(ZONE)))


def _telegram_cfg():
    # chat_ids (plural, a tuple): findplus.alerts.store.TelegramCreds' current
    # multi-target shape (findplus.alerts.dispatch._channel_targets reads it).
    return types.SimpleNamespace(
        telegram=types.SimpleNamespace(bot_token="t", chat_ids=("1",)), webhook=None, whatsapp=None
    )


def _send_ok():
    return types.SimpleNamespace(success=True, status_code=200, error=None)


def feed(
    register_provider,
    device_id,
    device_name,
    *,
    base: datetime,
    minutes_ago,
    lat,
    accuracy,
    settings,
) -> None:
    """One poll_device() call: the real ingest -> geofence -> group-quorum chain.

    `minutes_ago` (not an offset forward from `base`): the FakeProvider's fix
    is dated in the past, same as a real Find Hub report, while ingestion's
    own `fetched_at` is the real wall clock at THIS call, which runs within
    the same test-execution instant as every other call here -- keeping
    observed_at in the past is what keeps render_message()'s lag positive.
    """
    from findplus.providers.google_findhub.types import RawObservation

    obs = RawObservation(
        device_id=device_id,
        device_name=device_name,
        latitude_e7=round(lat * 1e7),
        longitude_e7=0,
        observed_at=base - timedelta(minutes=minutes_ago),
        accuracy_meters=accuracy,
        source="crowdsourced",
        is_own_report=False,
    )
    register_provider("test-fake", FakeProvider([obs]))
    outcome = poll_device(device_id, device_name, "test-fake", settings=settings)
    assert outcome.ok, outcome.error_message


def run_dispatch(session, now: datetime):
    """The real dispatch.process() at a fixed `now`, telegram's HTTP mocked.

    Returns the send mock so callers can assert on the exact rendered text --
    AlertDelivery itself stores only status/error, never the message body.
    """
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_cfg()),
        patch("findplus.alerts.channels.telegram.send", return_value=_send_ok()) as tg_mock,
    ):
        dispatch.process(dispatch.load_pending_events(session), session, _ALERTS_ON, now=now)
    return tg_mock


def assert_message(
    text: str,
    subject: str,
    verb: str,
    *,
    base: datetime,
    when_minutes_ago: float,
    confidence: str,
    note: str = "",
) -> None:
    """The deterministic parts of render_message(): local time+zone (R-P2-31),
    confidence (+ group note), and the alert-latency honesty sentence, verbatim.
    The "reported ... · N min late" clause is left loose (regex): it is built
    from the ingest call's real wall-clock fetched_at, not from `base`."""
    observed = local_time(base, when_minutes_ago)
    assert text.startswith(f"{subject} {verb} {PLACE_NAME}\nObserved {observed} · reported "), text
    tail = f"\nConfidence: {confidence}." + (f" {note}" if note else "")
    assert tail in text, text
    assert text.endswith(ALERTS_LATENCY), text
    assert re.search(
        r"reported (\w+ \d{1,2}, \d{1,2}:\d{2} [AP]M \w+|unknown) · (\d+ min late|lag unknown)",
        text,
    ), text


def seed_home(session, base: datetime) -> None:
    """Home: (0,0), radius 100m, the schema defaults (enter=1/exit=2 confirmations)."""
    session.add(
        Place(
            id=1,
            name=PLACE_NAME,
            latitude_e7=0,
            longitude_e7=0,
            radius_meters=100,
            enter_confirmations=1,
            exit_confirmations=2,
            created_at=base,
            updated_at=base,
        )
    )


def setup_home_rules(session, base: datetime) -> tuple[AlertRule, AlertRule]:
    """Home + a device leave/arrive rule pair, both on telegram and native."""
    seed_home(session, base)
    upsert_device(session, "dev1", "Tag1", provider="test-fake", now=base)
    leaves = AlertRule(
        name="leaves-home",
        place_id=1,
        device_id="dev1",
        on_enter=False,
        on_exit=True,
        channels=format_channels(["telegram", "native"]),
        cooldown_minutes=30,
        enabled=True,
        also_notify_members=False,
        created_at=base,
    )
    arrives = AlertRule(
        name="arrives-home",
        place_id=1,
        device_id="dev1",
        on_enter=True,
        on_exit=False,
        channels=format_channels(["telegram", "native"]),
        cooldown_minutes=15,
        enabled=True,
        also_notify_members=False,
        created_at=base,
    )
    session.add_all([leaves, arrives])
    session.commit()
    return leaves, arrives
