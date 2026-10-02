"""Flag checks do not rebuild Settings each tick; a hung loop is not "running" (r1 #10, #11)."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from findplus import poller_service
from findplus.api._helpers import _poller_appears_live
from findplus.poller_service import PollerService, loop_is_alive


def _service(state_dir) -> PollerService:
    service = PollerService.__new__(PollerService)
    service._stop = threading.Event()
    service._consecutive_failures = 0
    service.settings = SimpleNamespace(
        effective_poll_interval_minutes=5.0, poll_max_backoff_minutes=60, state_dir=state_dir
    )
    return service


def test_a_sleep_builds_settings_at_most_once(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(poller_service, "get_settings", lambda: calls.append(1))
    service = _service(tmp_path)
    service._sleep(2.2)  # about three one-second ticks
    assert calls == []  # the loop's own state_dir is used, nothing rebuilt


def test_the_flag_is_read_from_the_loops_own_state_dir(tmp_path) -> None:
    service = _service(tmp_path)
    threading.Timer(0.2, (tmp_path / "poller.wake").touch).start()
    start = time.monotonic()
    service._sleep(30.0)
    assert time.monotonic() - start < 5.0
    assert not (tmp_path / "poller.wake").exists()


SETTINGS = SimpleNamespace(effective_poll_interval_minutes=5.0, poll_max_backoff_minutes=60)


def test_a_fresh_heartbeat_is_alive_and_a_stale_one_is_not() -> None:
    now = time.monotonic()
    assert loop_is_alive(SETTINGS, {"heartbeat": now - 10, "failures": 0})
    # no failures: window = 5 min interval + 5 min backoff base + 60 s
    assert not loop_is_alive(SETTINGS, {"heartbeat": now - 700, "failures": 0})
    # three failures widen the window to 40 min + 5 min + 60 s
    assert loop_is_alive(SETTINGS, {"heartbeat": now - 2400, "failures": 3})
    assert not loop_is_alive(SETTINGS, {"heartbeat": now - 3000, "failures": 3})
    assert loop_is_alive(SETTINGS, {"heartbeat": None, "failures": 0})


def test_status_says_not_running_when_the_loop_heartbeat_is_stale(monkeypatch) -> None:
    monkeypatch.setattr(poller_service, "_running_here", 1)
    monkeypatch.setitem(poller_service._schedule, "heartbeat", time.monotonic() - 5000)
    monkeypatch.setitem(poller_service._schedule, "failures", 0)
    assert _poller_appears_live(None, SETTINGS) is False
    monkeypatch.setitem(poller_service._schedule, "heartbeat", time.monotonic())
    assert _poller_appears_live(None, SETTINGS) is True
