"""wake_poller() ends a backoff sleep early and clears the failure count."""

from __future__ import annotations

import threading
import time

from findplus import poller_service
from findplus.poller_service import PollerService, wake_poller


def test_wake_returns_early_and_resets_backoff() -> None:
    poller_service._WAKE.clear()
    service = PollerService.__new__(PollerService)
    service._stop = threading.Event()
    service._consecutive_failures = 4

    threading.Timer(0.2, wake_poller).start()
    start = time.monotonic()
    service._sleep(30.0)

    assert time.monotonic() - start < 5.0
    assert service._consecutive_failures == 0
    assert not poller_service._WAKE.is_set()


def test_sleep_without_wake_waits_the_delay() -> None:
    poller_service._WAKE.clear()
    service = PollerService.__new__(PollerService)
    service._stop = threading.Event()
    service._consecutive_failures = 2

    start = time.monotonic()
    service._sleep(0.3)

    assert time.monotonic() - start >= 0.25
    assert service._consecutive_failures == 2


def test_stop_ends_the_sleep() -> None:
    service = PollerService.__new__(PollerService)
    service._stop = threading.Event()
    service._consecutive_failures = 1
    service._stop.set()

    start = time.monotonic()
    service._sleep(30.0)

    assert time.monotonic() - start < 1.0


def test_wake_right_after_a_google_cycle_waits_out_the_gap(monkeypatch) -> None:
    """Review r1 #9: a wake that lands mid-cycle must not run a second cycle with zero gap."""
    monkeypatch.setattr(poller_service, "_MIN_WAKE_GAP_SECONDS", 0.6)
    poller_service._WAKE.clear()
    service = PollerService.__new__(PollerService)
    service._stop = threading.Event()
    service._consecutive_failures = 0
    service._last_traffic_end = time.monotonic()

    poller_service._WAKE.set()
    start = time.monotonic()
    service._sleep(30.0)

    assert 0.4 <= time.monotonic() - start < 5.0


def test_wake_after_a_quiet_cycle_is_immediate() -> None:
    poller_service._WAKE.clear()
    service = PollerService.__new__(PollerService)
    service._stop = threading.Event()
    service._consecutive_failures = 0
    service._last_traffic_end = None

    poller_service._WAKE.set()
    start = time.monotonic()
    service._sleep(30.0)

    assert time.monotonic() - start < 1.5
