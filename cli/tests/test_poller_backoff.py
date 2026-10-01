"""Backoff rules: no Google traffic means no backoff, and a wake or a manual poll ends one.

Purpose    : A locked key or a signed-out account makes zero Google requests, so
             those polls must not climb the 5/10/20/60 minute ladder; poll-now
             resets it; a CLI process (unlock, token, poll-now) wakes the daemon
             through a flag file; /api/status reports the loop's own next attempt.
Constraints: Fake poll cycles, tiny intervals, isolated state dir, no network.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from findplus import poller_service
from findplus.config import get_settings
from findplus.poller_outcomes import CycleOutcome, PollOutcome
from findplus.poller_service import PollerService, reset_backoff, wake_poller


def _service(failures: int = 0, interval_minutes: float = 5.0) -> PollerService:
    service = PollerService.__new__(PollerService)
    service._stop = threading.Event()
    service._consecutive_failures = failures
    service.settings = SimpleNamespace(
        effective_poll_interval_minutes=interval_minutes, poll_max_backoff_minutes=60
    )
    return service


def _cycle(*statuses: str) -> CycleOutcome:
    return CycleOutcome([PollOutcome(status=s) for s in statuses])


@pytest.mark.parametrize("status", ["needs_shared_key", "provider_unauthenticated"])
def test_a_poll_that_never_reached_google_does_not_escalate_backoff(status: str) -> None:
    assert _cycle(status).no_google_traffic is True


def test_a_real_failure_still_escalates() -> None:
    assert _cycle("timeout").no_google_traffic is False
    assert _cycle("decrypt_failed").no_google_traffic is False
    assert _cycle("needs_shared_key", "timeout").no_google_traffic is False


def test_the_loop_keeps_failures_at_zero_while_locked() -> None:
    service = _service()
    cycles = iter([_cycle("needs_shared_key")] * 3)
    delays: list[float] = []

    def fake_poll_once(*_a, **_k):
        try:
            return next(cycles)
        except StopIteration:
            service._stop.set()
            return _cycle("needs_shared_key")

    service._sleep = lambda delay: delays.append(delay)  # type: ignore[method-assign]
    service._loop(fake_poll_once)
    assert service._consecutive_failures == 0
    assert set(delays) == {300.0}


def test_reset_backoff_shortens_a_long_sleep_and_clears_failures() -> None:
    service = _service(failures=4, interval_minutes=0.01)  # 0.6 s interval
    threading.Timer(0.2, reset_backoff).start()
    start = time.monotonic()
    service._sleep(30.0)
    assert time.monotonic() - start < 5.0
    assert service._consecutive_failures == 0


def test_a_flag_file_from_another_process_wakes_the_loop() -> None:
    service = _service(failures=3)
    flag = get_settings().state_dir / "poller.wake"

    def other_process() -> None:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.touch()

    threading.Timer(0.2, other_process).start()
    start = time.monotonic()
    service._sleep(30.0)
    assert time.monotonic() - start < 5.0
    assert service._consecutive_failures == 0
    assert not flag.exists()


def test_wake_and_reset_from_a_process_without_a_loop_leave_flag_files() -> None:
    state = get_settings().state_dir
    wake_poller()
    reset_backoff()
    assert (state / "poller.wake").exists()
    assert (state / "poller.reset").exists()
    poller_service._WAKE.clear()
    poller_service._RESET.clear()


def test_status_next_poll_includes_the_backoff(client, monkeypatch: pytest.MonkeyPatch) -> None:
    due = datetime.now(UTC) + timedelta(minutes=40)
    monkeypatch.setattr(poller_service, "_running_here", 1)
    monkeypatch.setitem(poller_service._schedule, "next_attempt_at", due)
    monkeypatch.setitem(poller_service._schedule, "busy", False)
    monkeypatch.setitem(poller_service._schedule, "heartbeat", time.monotonic())
    body = client.get("/api/status").json()
    assert body["poller_running"] is True
    assert body["next_poll_at"].startswith(due.strftime("%Y-%m-%dT%H:%M"))
