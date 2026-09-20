"""alerts/dispatch.py: webhook payload lag_minutes -- null when fetched_at is unknown.

Purpose : Cover the 2026-09-19 engines.md ruling (Webhook JSON: "lag_minutes":
          int|null, never 0 for unknown) -- a GroupEvent carries no fetched_at
          at all, and a DeviceEvent can lack one too. Split into its own file
          rather than growing test_dispatch.py / test_dispatch_cooldown.py
          past the 300-line cap.
Inputs  : DeviceEvent/GroupEvent dataclasses, a webhook-channel Rule, a
          mocked send_webhook capturing the payload dispatch._send built.
Outputs : n/a (pytest assertions).
Constraints: No DB session, no network -- send_webhook itself is mocked.
"""

from __future__ import annotations

import types
from datetime import timedelta
from unittest.mock import patch

from findplus.alerts.dispatch import Rule
from findplus.alerts.dispatch_send import _send

from ._helpers import NOW, _device_event, _group_event


def _webhook_configured():
    return types.SimpleNamespace(
        telegram=None,
        webhook=types.SimpleNamespace(url="https://example.test/hook", secret=None),
    )


def _webhook_rule(**overrides) -> Rule:
    base = dict(
        id=1,
        name="webhook-rule",
        place_id=None,
        group_id=None,
        device_id=None,
        on_enter=True,
        on_exit=True,
        channels="webhook",
        cooldown_minutes=0,
        enabled=True,
        also_notify_members=False,
    )
    base.update(overrides)
    return Rule(**base)


def _sent_payload(send_mock) -> dict:
    return send_mock.call_args.args[0]


def test_group_event_webhook_lag_minutes_is_null() -> None:
    """A GroupEvent has no fetched_at -- the payload must send null, never 0."""
    with patch("findplus.alerts.channels.webhook.send_webhook") as send_mock:
        send_mock.return_value = types.SimpleNamespace(success=True, status_code=200, error=None)
        _send("webhook", _webhook_rule(), _group_event(), "group", "msg", _webhook_configured())
    assert _sent_payload(send_mock)["lag_minutes"] is None


def test_device_event_webhook_lag_minutes_reflects_a_five_minute_delay() -> None:
    event = _device_event(fetched_at=NOW + timedelta(minutes=5))
    with patch("findplus.alerts.channels.webhook.send_webhook") as send_mock:
        send_mock.return_value = types.SimpleNamespace(success=True, status_code=200, error=None)
        _send("webhook", _webhook_rule(), event, "device", "msg", _webhook_configured())
    assert _sent_payload(send_mock)["lag_minutes"] == 5


def test_device_event_webhook_lag_minutes_is_null_without_fetched_at() -> None:
    """Not just GroupEvent -- a DeviceEvent missing fetched_at is unknown too."""
    event = _device_event(fetched_at=None)
    with patch("findplus.alerts.channels.webhook.send_webhook") as send_mock:
        send_mock.return_value = types.SimpleNamespace(success=True, status_code=200, error=None)
        _send("webhook", _webhook_rule(), event, "device", "msg", _webhook_configured())
    assert _sent_payload(send_mock)["lag_minutes"] is None
