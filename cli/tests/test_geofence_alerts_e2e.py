"""End to end: real fixes through the poller drive geofence and device alerts.

Purpose    : Prove the "tracker leaves Home" scenario -- observation ingestion
             -> place state change -> rule match -> delivery row -> channel
             send -- through poll_device(), the poller's real per-device
             processing function, not through a hand-seeded place_events row.
             Every earlier alerts test (cli/tests/alerts/test_dispatch*.py)
             starts from a place_events row built by hand; none of them drive
             the real geofence engine from raw fixes first. A quorum='any'
             group rule on the same scenario is covered separately in
             test_geofence_alerts_e2e_group.py (PRI 300-line file cap).
Inputs     : A FakeProvider feeding one fix per poll_device() call at a Home
             place ((0,0), radius 100m). The only other mock is the outbound
             HTTP call in findplus.alerts.channels.telegram.send. Shared
             builders live in geofence_alerts_helpers.py.
Outputs    : n/a (pytest assertions).
Constraints: Never touches the network or the real ~/.findplus (conftest.py's
             autouse fixtures already enforce this).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from findplus.alerts import dispatch
from findplus.alerts.dispatch import Delivery, DeviceEvent, Rule, in_cooldown
from findplus.config import Settings
from findplus.db.models import PlaceEvent, PlaceState
from findplus.db.models_alerts import AlertDelivery, AlertRule
from tests.geofence_alerts_helpers import (
    EDGE_LAT,
    OUTSIDE_LAT,
    PLACE_NAME,
    ZONE,
    assert_message,
    feed,
    run_dispatch,
    setup_home_rules,
)


def _assert_no_repeat_while_away(
    session, register_provider, base: datetime, ingest_settings
) -> None:
    """A late/backfilled fix that looks like an arrival, and a poor-accuracy fix
    right at the edge, must neither flap the state nor produce a new alert.

    The backfilled fix is dated 18 minutes ago, BEFORE the EXIT's own
    since_observed_at (10 minutes ago): geofence.advance()'s backfill guard
    must ignore it even though its coordinates alone would read as "at Home"
    -- a stale/out-of-order report is never read as an arrival. The edge fix
    is dated 8 minutes ago (after the exit) so it is evaluated fresh, not
    caught by the backfill guard -- it is ignored on its own low-confidence
    merits instead (poor accuracy near the edge must not flap the state).
    """
    feed(
        register_provider,
        "dev1",
        "Tag1",
        base=base,
        minutes_ago=18,
        lat=0.0,
        accuracy=20,
        settings=ingest_settings,
    )
    feed(
        register_provider,
        "dev1",
        "Tag1",
        base=base,
        minutes_ago=8,
        lat=EDGE_LAT,
        accuracy=150,
        settings=ingest_settings,
    )
    session.expire_all()
    assert dispatch.load_pending_events(session) == []
    assert session.get(PlaceState, (1, "dev1")).state == "outside"
    assert session.query(PlaceEvent).count() == 1


def _assert_cooldown_would_suppress_repeat(
    leaves_rule: AlertRule, base: datetime, exit_event_id: int, sent_at
) -> None:
    """Same (rule, channel, place, subject) key inside cooldown_minutes must suppress a repeat.

    `sent_at` is the real delivery row's own sent_at (dispatch ran at `now=base`
    for the exit); checked 4 minutes later, still well inside the 30-minute
    cooldown_minutes on the "leaves" rule.
    """
    delivered = Delivery(
        rule_id=leaves_rule.id,
        event_kind="device",
        event_id=exit_event_id,
        sent_at=sent_at,
        channel="telegram",
        status="sent",
        place_id=1,
    )
    later = base + timedelta(minutes=4)
    hypothetical = DeviceEvent(
        place_event_id=999999,
        place_id=1,
        place_name=PLACE_NAME,
        device_id="dev1",
        device_name="Tag1",
        event_type="EXIT",
        observed_at=later,
        fetched_at=None,
        confidence="high",
        group_ids=[],
    )
    rule_dc = Rule(
        id=leaves_rule.id,
        name=leaves_rule.name,
        place_id=1,
        group_id=None,
        device_id="dev1",
        on_enter=False,
        on_exit=True,
        channels=["telegram", "native"],
        cooldown_minutes=leaves_rule.cooldown_minutes,
        enabled=True,
        also_notify_members=False,
    )
    assert in_cooldown(rule_dc, "telegram", hypothetical, [delivered], now=later)


def _delivery_status(session, rule_id: int) -> dict[str, str]:
    rows = session.query(AlertDelivery).filter_by(rule_id=rule_id).all()
    return {row.channel: row.status for row in rows}


def _fix_home(
    register_provider, base, settings, minutes_ago: float, lat: float, accuracy=20
) -> None:
    """One dev1 fix, `minutes_ago` in the past (see geofence_alerts_helpers.feed)."""
    feed(
        register_provider,
        "dev1",
        "Tag1",
        base=base,
        minutes_ago=minutes_ago,
        lat=lat,
        accuracy=accuracy,
        settings=settings,
    )


def test_leaves_home_once_then_returns_end_to_end(session, register_provider, pinned_tz) -> None:
    """inside -> outside x2 (EXIT once) -> stale backfill + poor-accuracy edge fix
    (both ignored, no flap) -> inside again (ENTER). Only the provider and
    telegram's outbound HTTP are mocked; ingest/geofence/dispatch are real."""
    pinned_tz(ZONE)
    base = datetime.now(UTC)
    leaves, arrives = setup_home_rules(session, base)
    ingest_settings = Settings(alerts_enabled=False)

    # inside 20min ago -> outside 15min ago -> outside 10min ago (EXIT).
    _fix_home(register_provider, base, ingest_settings, 20, 0.0)
    _fix_home(register_provider, base, ingest_settings, 15, OUTSIDE_LAT)
    _fix_home(register_provider, base, ingest_settings, 10, OUTSIDE_LAT)

    session.expire_all()
    exits = session.query(PlaceEvent).filter_by(event_type="EXIT").all()
    assert len(exits) == 1, "hysteresis must confirm the exit exactly once"

    tg_mock = run_dispatch(session, now=base)
    assert tg_mock.call_count == 1
    assert_message(
        tg_mock.call_args[0][0], "Tag1", "left", base=base, when_minutes_ago=10, confidence="high"
    )
    assert _delivery_status(session, leaves.id) == {"telegram": "sent", "native": "queued"}
    exit_row = session.query(AlertDelivery).filter_by(rule_id=leaves.id, channel="telegram").one()

    _assert_no_repeat_while_away(session, register_provider, base, ingest_settings)
    _assert_cooldown_would_suppress_repeat(leaves, base, exits[0].id, exit_row.sent_at)

    _fix_home(register_provider, base, ingest_settings, 0, 0.0)  # back inside -> ENTER.
    tg_mock2 = run_dispatch(session, now=base)
    assert tg_mock2.call_count == 1
    assert_message(
        tg_mock2.call_args[0][0],
        "Tag1",
        "arrived at",
        base=base,
        when_minutes_ago=0,
        confidence="high",
    )
    assert _delivery_status(session, arrives.id) == {"telegram": "sent", "native": "queued"}
