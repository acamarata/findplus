"""Shared fake-result builders for the retry-ladder test suite, split out of
test_dispatch_retry.py (E13 stage 2, size cap).

Purpose    : One definition of the fake channel-send results (timeout,
             success, permanent 4xx, rate-limited) and the seed+process
             helper both test_dispatch_retry.py and test_dispatch_retry_drain.py
             need.
Inputs     : n/a (pure builders); `_seed_and_process` takes the same
             rule_row/session/settings_enabled fixtures the tests do.
Outputs    : `types.SimpleNamespace` objects shaped like a channel send result.
Constraints: test-only; never imported by cli/src.
"""

from __future__ import annotations

import types

from findplus.alerts.dispatch import load_pending_events, process

from ._helpers import NOW, _seed_pending_place_event, _telegram_configured


def _timeout():
    return types.SimpleNamespace(success=False, status_code=None, error="timeout")


def _sent():
    return types.SimpleNamespace(success=True, status_code=200, error=None)


def _bad_request():
    return types.SimpleNamespace(success=False, status_code=400, error="bad request")


def _rate_limited(retry_after):
    return types.SimpleNamespace(
        success=False, status_code=429, error="rate limited", retry_after_seconds=retry_after
    )


def _seed_and_process(rule_row, session, settings_enabled, result):
    from unittest.mock import patch

    _seed_pending_place_event(session, place_id=1, observed_at=NOW)
    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send", return_value=result),
    ):
        process(load_pending_events(session), session, settings_enabled, now=NOW)
