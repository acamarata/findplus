"""The background update loop: a developer-folder scan each minute, GitHub every 6 hours.

Purpose    : Keep `staged` current without the owner doing anything. Runs in the
             daemon beside retention and the evening summary.
Inputs     : `updates.auto` and `updates.dev_dir` (re-read every tick), a clock.
Outputs    : Calls into check.py; log lines.
Constraints: With `updates.auto` off, no request leaves this computer. The first
             tick after a start checks GitHub only when the last check is over an
             hour old, so frequent restarts do not repeat it. A failing tick is
             logged and the loop carries on.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from findplus.config import get_settings
from findplus.db.session import session_scope
from findplus.logging_setup import get_logger
from findplus.updater import devsource, prefs, store
from findplus.updater.check import check, scan_dev
from findplus.updater.status import can_install_here, tidy

log = get_logger(__name__)

TICK_SECONDS = 60.0
CHECK_EVERY = timedelta(hours=6)
STARTUP_GAP = timedelta(hours=1)


def is_due(checked_at: object, now: datetime, first: bool) -> bool:
    """A GitHub check is due 6 h after the last one (1 h on the first tick after a start)."""
    try:
        last = datetime.fromisoformat(str(checked_at))
    except ValueError:
        return True
    if last > now:  # a clock moved back: check again rather than wait for ever
        return True
    return now - last >= (STARTUP_GAP if first else CHECK_EVERY)


class UpdateScheduler:
    """Calls `tick()` every minute until `stop()`."""

    def __init__(
        self,
        state_dir: Path | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        interval: float = TICK_SECONDS,
    ) -> None:
        self._state_dir = state_dir
        self._clock = clock or (lambda: datetime.now(UTC))
        self._interval = interval
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run_forever(self) -> None:
        log.info("update_scheduler_started")
        first = True
        while not self._stop.is_set():
            try:
                self.tick(first=first)
            except Exception as exc:  # a bad tick must not end the loop
                log.warning("update_tick_failed", error=str(exc))
            first = False
            self._stop.wait(self._interval)
        log.info("update_scheduler_stopped")

    def tick(self, *, first: bool = False) -> str:
        """One pass. Returns what it did: off | dev | checked | idle."""
        state_dir = get_settings(self._state_dir).state_dir
        with session_scope() as session:
            auto = prefs.auto_enabled(session)
            dev_dir = devsource.dev_dir(session)
        if first:
            tidy(state_dir)
        if not auto:
            return "off"
        now = self._clock()
        if is_due(store.load(state_dir).get("checked_at"), now, first):
            check(state_dir, download=can_install_here(), dev_dir=dev_dir, now=now)
            return "checked"
        if dev_dir is not None:
            scan_dev(state_dir, dev_dir)
            return "dev"
        return "idle"
