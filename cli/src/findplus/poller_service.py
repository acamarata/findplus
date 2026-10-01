"""The forever-running poll loop, with exponential backoff.

Purpose : Run `poll_once` on a schedule until stopped, backing off on
          consecutive whole-cycle failures. Split out of `poller.py` (E13
          loop2 A3) so that module stays inside the 300-line file cap; no
          behavior change.
Inputs  : Settings (poll interval, backoff cap, fast-polling opt-in).
Outputs : `PollerService.last_cycle`; structured log lines.
Constraints: A config error (e.g. no devices tracked) resets backoff instead
    of extending it -- see `run_forever`'s comment. Re-exported by
    `findplus.poller`, so `from findplus.poller import PollerService` keeps
    resolving exactly as before the split.
"""

from __future__ import annotations

import contextlib
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from findplus.config import Settings, get_settings
from findplus.db.session import session_scope
from findplus.logging_setup import get_logger
from findplus.poller_outcomes import CycleOutcome
from findplus.state import get_tracked_devices

log = get_logger(__name__)

# Set by `wake_poller()` (e.g. right after an unlock or sign-in) so the loop
# polls now and clears its backoff instead of sleeping out the failures that
# came from the missing credential.
_WAKE = threading.Event()
# Set by `reset_backoff()` (a manual poll worked): clear the failure count and
# sleep a normal interval from now, without polling again straight away.
_RESET = threading.Event()

#: How many PollerService loops run in THIS process. A wake from the daemon's own
#: process uses the Events; a CLI process (`findplus auth --unlock`, `poll-now`)
#: cannot reach them, so it leaves a small flag file the loop checks every second.
_running_here = 0

#: The live loop's own view of itself, for /api/status (next attempt, backoff).
_schedule: dict[str, object] = {
    "next_attempt_at": None,
    "failures": 0,
    "busy": False,
    "heartbeat": None,  # time.monotonic() of the loop's last sign of life
}


def _flag_path(name: str, base: Path | None = None) -> Path:
    return (base if base is not None else get_settings().state_dir) / f"poller.{name}"


def _touch_flag(name: str) -> None:
    with contextlib.suppress(OSError):
        path = _flag_path(name)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.touch(mode=0o600)


def _take_flag(name: str, base: Path | None = None) -> bool:
    """Consume a flag file. `base` is the state dir, resolved once by a caller that
    polls every second (building Settings each tick costs real CPU over a day)."""
    try:
        _flag_path(name, base).unlink()
    except OSError:
        return False
    return True


def wake_poller() -> None:
    """Ask the running poller to poll immediately and reset its backoff.

    Works from any process: the daemon's own loop sees the Event, a loop in
    another process sees the flag file within a second.
    """
    _WAKE.set()
    if not _running_here:
        _touch_flag("wake")


def reset_backoff() -> None:
    """A poll worked by hand: drop the failure count so the loop stops sleeping out a backoff."""
    _RESET.set()
    if not _running_here:
        _touch_flag("reset")


def schedule_snapshot() -> dict[str, object] | None:
    """`{next_attempt_at, failures, busy, heartbeat}` of the poll loop in THIS process, or None."""
    if not _running_here:
        return None
    return dict(_schedule)


def loop_is_alive(settings: Settings, snapshot: dict[str, object]) -> bool:
    """False when the loop has shown no sign of life for longer than backoff + interval.

    The loop beats every sleeping second and at each cycle start, so only a cycle
    that never returns (a hung FCM wait or chromedriver) outlasts the window.
    """
    beat = snapshot.get("heartbeat")
    if not isinstance(beat, float):
        return True  # not beaten yet: the loop has only just started
    interval = settings.effective_poll_interval_minutes * 60.0
    failures = int(snapshot.get("failures") or 0)
    backoff = min(interval * 2 ** min(failures, 6), settings.poll_max_backoff_minutes * 60.0)
    return time.monotonic() - beat <= backoff + interval + 60.0


#: A wake that lands right after a cycle that reached Google waits this long (review r1 #9).
_MIN_WAKE_GAP_SECONDS = 30.0


class PollerService:
    """Runs a poll cycle forever with backoff. Stoppable via `stop()`."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._stop = threading.Event()
        self._consecutive_failures = 0
        self.last_cycle: CycleOutcome | None = None
        #: When the last cycle that reached Google ended; a wake right after it waits out
        #: _MIN_WAKE_GAP_SECONDS instead of running a second cycle back to back.
        self._last_traffic_end: float | None = None

    def stop(self) -> None:
        self._stop.set()

    def _next_delay_seconds(self) -> float:
        base = self.settings.effective_poll_interval_minutes * 60.0
        if self._consecutive_failures == 0:
            return base
        backoff = base * (2 ** min(self._consecutive_failures, 6))
        return min(backoff, self.settings.poll_max_backoff_minutes * 60.0)

    def _publish(self, delay: float | None, busy: bool = False) -> None:
        """Record when the next attempt is due, for the status API."""
        _schedule["failures"] = self._consecutive_failures
        _schedule["busy"] = busy
        _schedule["heartbeat"] = time.monotonic()
        _schedule["next_attempt_at"] = (
            None if delay is None else datetime.now(UTC) + timedelta(seconds=delay)
        )

    def _wake_gap_left(self) -> float:
        """Seconds a wake must still wait: zero unless a cycle that reached Google just ended."""
        ended = getattr(self, "_last_traffic_end", None)
        if ended is None:
            return 0.0
        return _MIN_WAKE_GAP_SECONDS - (time.monotonic() - ended)

    def _sleep(self, delay: float) -> None:
        """Wait `delay` seconds, returning early on stop or `wake_poller()`.

        `reset_backoff()` drops the failure count and shortens the wait to one
        normal interval from now.
        """
        end = time.monotonic() + delay
        self._publish(delay)
        settings = getattr(self, "settings", None)
        state_dir = getattr(settings, "state_dir", None) or get_settings().state_dir
        while not self._stop.is_set():
            woke = _WAKE.is_set()
            if _take_flag("wake", state_dir) or woke:
                _WAKE.clear()
                self._consecutive_failures = 0
                gap = self._wake_gap_left()
                if gap <= 0:
                    self._publish(0)
                    return
                end = min(end, time.monotonic() + gap)
                self._publish(gap)
            reset = _RESET.is_set()
            if _take_flag("reset", state_dir) or reset:
                _RESET.clear()
                self._consecutive_failures = 0
                settings = settings or get_settings()
                end = min(end, time.monotonic() + settings.effective_poll_interval_minutes * 60.0)
                self._publish(end - time.monotonic())
            _schedule["heartbeat"] = time.monotonic()
            left = end - time.monotonic()
            if left <= 0:
                return
            self._stop.wait(min(left, 1.0))

    def run_forever(self) -> None:
        import os

        from findplus.poller import poll_once

        interval = self.settings.effective_poll_interval_minutes
        if self.settings.allow_fast_polling and self.settings.poll_interval_minutes < 5:
            log.warning(
                "fast_polling_enabled",
                interval_minutes=interval,
                note="Polling faster than 5 minutes risks Google rate-limiting "
                "or account flags. This was explicitly opted into.",
            )

        with session_scope() as session:
            tracked = len(get_tracked_devices(session))
        log.info(
            "poller_started",
            interval_minutes=interval,
            tracked_devices=tracked,
            requests_per_hour=round(tracked * 60 / interval, 1) if interval else None,
            pid=os.getpid(),
        )

        global _running_here
        _running_here += 1
        _take_flag("wake")  # a flag left while no loop ran is stale: this loop polls now anyway
        _take_flag("reset")
        try:
            self._loop(poll_once)
        finally:
            _running_here -= 1
            _schedule["next_attempt_at"] = None
        log.info("poller_stopped")

    def _loop(self, poll_once) -> None:
        while not self._stop.is_set():
            self._publish(None, busy=True)
            cycle = poll_once(self.settings, stop_event=self._stop)
            self.last_cycle = cycle
            self._last_traffic_end = (
                None if cycle.config_error or cycle.no_google_traffic else time.monotonic()
            )
            if cycle.ok or cycle.config_error or cycle.no_google_traffic:
                # A config error, a locked key or a signed-out account means "nothing
                # to do yet": no Google request was made, so there is nothing to back off.
                # Retrying on the normal interval lets the daemon pick up a device
                # selection promptly instead of sitting in an hour-long backoff.
                self._consecutive_failures = 0
            else:
                self._consecutive_failures += 1

            delay = self._next_delay_seconds()
            if self._consecutive_failures:
                log.warning(
                    "poll_backoff",
                    consecutive_failures=self._consecutive_failures,
                    next_attempt_in_seconds=round(delay),
                )
            self._sleep(delay)
