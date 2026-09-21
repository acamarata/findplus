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

import threading

from findplus.config import Settings, get_settings
from findplus.db.session import session_scope
from findplus.logging_setup import get_logger
from findplus.poller_outcomes import CycleOutcome
from findplus.state import get_tracked_devices

log = get_logger(__name__)


class PollerService:
    """Runs a poll cycle forever with backoff. Stoppable via `stop()`."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._stop = threading.Event()
        self._consecutive_failures = 0
        self.last_cycle: CycleOutcome | None = None

    def stop(self) -> None:
        self._stop.set()

    def _next_delay_seconds(self) -> float:
        base = self.settings.effective_poll_interval_minutes * 60.0
        if self._consecutive_failures == 0:
            return base
        backoff = base * (2 ** min(self._consecutive_failures, 6))
        return min(backoff, self.settings.poll_max_backoff_minutes * 60.0)

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

        while not self._stop.is_set():
            cycle = poll_once(self.settings, stop_event=self._stop)
            self.last_cycle = cycle
            if cycle.ok or cycle.config_error:
                # A config error means "nothing to do yet", not "Google is failing".
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
            self._stop.wait(delay)

        log.info("poller_stopped")
