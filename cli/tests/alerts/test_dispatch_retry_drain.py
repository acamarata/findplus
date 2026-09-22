"""alerts/retry.py: drain bounding, supersession, unconfigured channels and
same-text-on-retry. Split from test_dispatch_retry.py (E13 stage 2, size cap).
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from findplus.alerts.dispatch import load_pending_events, process
from findplus.alerts.retry import process_retries
from findplus.db.models import PlaceEvent
from findplus.db.models_alerts import AlertDelivery

from ._helpers import NOW, _seed_pending_place_event, _seed_place_and_device, _telegram_configured
from ._retry_helpers import _seed_and_process, _sent, _timeout


def test_retry_drain_is_bounded_per_cycle(rule_row, session, settings_enabled):
    """R2: 1000 due retries must not be processed synchronously in one call --
    the poller has to keep ticking. Each call drains at most RETRY_DRAIN_LIMIT
    rows, oldest-due first, so the backlog empties progressively."""
    from findplus.alerts.retry import RETRY_DRAIN_LIMIT

    # cooldown_minutes=0 isolates R2 (drain bounding) from R4 (supersession):
    # 1000 events at the same place would otherwise cool each other down
    # once the first one of a batch sends, which is correct R4 behavior but
    # not what this test is about.
    rule_row.cooldown_minutes = 0
    session.commit()
    _seed_place_and_device(session)
    for i in range(1000):
        # observed_at must be distinct: location_observations is unique on
        # (device_id, observed_at, lat, lon).
        _seed_pending_place_event(session, place_id=1, observed_at=NOW + timedelta(seconds=i))
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send", return_value=_timeout()),
    ):
        process(load_pending_events(session), session, settings_enabled, now=NOW)

    assert session.query(AlertDelivery).filter_by(status="retrying").count() == 1000

    due = NOW + timedelta(minutes=1)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send", return_value=_sent()),
    ):
        processed_first = process_retries(session, now=due)
    assert processed_first == RETRY_DRAIN_LIMIT
    session.expire_all()
    assert session.query(AlertDelivery).filter_by(status="sent").count() == RETRY_DRAIN_LIMIT
    remaining = session.query(AlertDelivery).filter_by(status="retrying").count()
    assert remaining == 1000 - RETRY_DRAIN_LIMIT

    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send", return_value=_sent()),
    ):
        processed_second = process_retries(session, now=due)
    assert processed_second == RETRY_DRAIN_LIMIT
    session.expire_all()
    assert session.query(AlertDelivery).filter_by(status="sent").count() == 2 * RETRY_DRAIN_LIMIT


def test_successful_retry_updates_sent_at_to_the_real_send_time(
    rule_row, session, settings_enabled
):
    """R3: a successful retry must move sent_at to when it actually sent, or
    in_cooldown() (keyed on sent_at) would run the next cooldown from the
    original failure instead of the real send."""
    _seed_and_process(rule_row, session, settings_enabled, _timeout())
    later = NOW + timedelta(minutes=1)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send", return_value=_sent()),
    ):
        process_retries(session, now=later)
    session.expire_all()
    row = session.query(AlertDelivery).one()
    assert row.status == "sent"
    assert row.sent_at == later


def test_retry_superseded_by_a_newer_delivery_is_skipped_not_sent(
    rule_row, session, settings_enabled
):
    """R4: a fresh crossing sent (and cooled down) the same rule/channel/place
    key after this row's own first failure -- the stale retry must not
    resend and must not silently disappear either."""
    _seed_and_process(rule_row, session, settings_enabled, _timeout())
    row = session.query(AlertDelivery).one()
    assert row.status == "retrying"

    # A second, later crossing at the same place/device -- a genuinely new
    # event_id, per the widened uq_alert_deliveries_dedup(rule_id,
    # event_kind, event_id, channel) -- that was sent and started this same
    # cooldown key (rule, channel, place) after the stale row's own failure.
    newer_sent_at = row.sent_at + timedelta(seconds=30)
    _seed_pending_place_event(session, place_id=1, observed_at=newer_sent_at)
    newer_event_id = session.query(PlaceEvent).order_by(PlaceEvent.id.desc()).first().id
    session.add(
        AlertDelivery(
            rule_id=row.rule_id,
            event_kind=row.event_kind,
            event_id=newer_event_id,
            channel=row.channel,
            sent_at=newer_sent_at,
            status="sent",
            attempts=1,
        )
    )
    session.commit()

    due = NOW + timedelta(minutes=1)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send") as mock_send,
    ):
        processed = process_retries(session, now=due)
    assert mock_send.call_count == 0, "a superseded retry must never call send()"
    assert processed == 1
    session.expire_all()
    row = session.query(AlertDelivery).filter_by(id=row.id).one()
    assert row.status == "skipped"
    assert row.next_attempt_at is None


def test_retry_of_an_unconfigured_channel_is_skipped_not_failed(
    rule_row, session, settings_enabled
):
    """R5: a channel removed/unconfigured while a row was backing off must
    land on "skipped" (dispatch_send._status_for's own classification),
    never overwritten to "failed"."""
    _seed_and_process(rule_row, session, settings_enabled, _timeout())
    due = NOW + timedelta(minutes=1)
    with patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured(none=True)):
        process_retries(session, now=due)
    session.expire_all()
    row = session.query(AlertDelivery).one()
    assert row.status == "skipped"
    assert row.error == "telegram is not configured"
    assert row.next_attempt_at is None


def test_retry_renders_the_same_text_the_first_attempt_would(rule_row, session, settings_enabled):
    """R7: render_message()'s only time-dependent choice is same-day vs.
    full-date formatting. A retry due the next local day must still render
    the exact text the first attempt rendered, not a version that suddenly
    grew a date because the retry landed later."""
    captured: list[str] = []

    def _capturing_send(text, *args, **kwargs):
        captured.append(text)
        return _timeout()

    _seed_and_process(rule_row, session, settings_enabled, _timeout())
    row = session.query(AlertDelivery).one()

    much_later = row.sent_at + timedelta(days=2)  # crosses the same-day boundary
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send", side_effect=_capturing_send),
    ):
        process_retries(session, now=much_later)

    assert len(captured) == 1
    # Sanity: rendering with `much_later` as "now" would have produced a
    # DIFFERENT string (the observation is no longer "today") -- this proves
    # the test can fail, not just that some string was sent.
    from findplus.alerts.dispatch_core import render_message

    first_attempt_text = render_message(_device_event_from_row(session, row), row.sent_at)
    later_rendered_text = render_message(_device_event_from_row(session, row), much_later)
    assert captured[0] == first_attempt_text
    assert first_attempt_text != later_rendered_text


def _device_event_from_row(session, row):
    from findplus.alerts.retry import _load_event

    return _load_event(session, row.event_kind, row.event_id)
