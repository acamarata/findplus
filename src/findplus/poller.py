"""The polling service.

Purpose : Query Find Hub for every tracked device on a schedule, persist new
          observations, and record health.
Constraints:
    - Tracking N devices costs N Google requests per cycle. Devices are polled
      SEQUENTIALLY with a stagger, never as a burst, to stay gentle on the
      account. `effective_request_interval_seconds` reports the real rate.
    - A failed poll NEVER crashes the daemon, and one device failing never stops
      the others. Every outcome is written to `poll_runs` per device.
    - Consecutive whole-cycle failures apply exponential backoff, capped by
      `poll_max_backoff_minutes`. Any success resets it.
    - A missed wake-up (machine asleep) is not an error; the loop simply runs late.
    - Locations are never fabricated. A poll returning nothing records
      `status="no_location"` and stores no coordinates.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime

from findplus.config import Settings, get_settings
from findplus.db.models import PollRun
from findplus.db.session import session_scope
from findplus.findhub.client import FindHubClient
from findplus.findhub.types import (
    AuthRequiredError,
    DecryptionError,
    FindHubError,
    LocationTimeoutError,
)
from findplus.ingest import ingest_observations
from findplus.logging_setup import get_logger
from findplus.state import get_tracked_devices

log = get_logger(__name__)

#: Seconds between consecutive device requests inside one cycle.
DEVICE_STAGGER_SECONDS = 10.0


@dataclass(slots=True)
class PollOutcome:
    """Result of polling ONE device."""

    status: str
    device_id: str | None = None
    device_name: str | None = None
    received: int = 0
    inserted: int = 0
    duplicates: int = 0
    error_type: str | None = None
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in {"ok", "no_location"}


@dataclass(slots=True)
class CycleOutcome:
    """Result of polling every tracked device once."""

    outcomes: list[PollOutcome] = field(default_factory=list)
    #: True when the cycle did nothing because nothing is configured to be polled.
    #: This is a configuration state, not a Google failure, so it must NOT escalate
    #: backoff — otherwise the daemon would still be sleeping for an hour right
    #: after the user finally selects their devices.
    config_error: bool = False

    @property
    def ok(self) -> bool:
        """True when at least one device succeeded, or there was nothing to do."""
        return not self.outcomes or any(o.ok for o in self.outcomes)

    @property
    def inserted(self) -> int:
        return sum(o.inserted for o in self.outcomes)

    @property
    def duplicates(self) -> int:
        return sum(o.duplicates for o in self.outcomes)

    @property
    def received(self) -> int:
        return sum(o.received for o in self.outcomes)


def poll_device(
    device_id: str,
    device_name: str,
    client: FindHubClient | None = None,
    settings: Settings | None = None,
) -> PollOutcome:
    """Poll a single device and record the attempt. Never raises on poll failure."""
    settings = settings or get_settings()
    client = client or FindHubClient(settings)
    started = datetime.now(UTC)
    observations = None

    try:
        observations = client.locate(device_id, device_name)
    except AuthRequiredError as exc:
        outcome = PollOutcome(
            status="auth_error", error_type="AuthRequiredError", error_message=str(exc)
        )
    except LocationTimeoutError as exc:
        outcome = PollOutcome(
            status="timeout", error_type="LocationTimeoutError", error_message=str(exc)
        )
    except DecryptionError as exc:
        outcome = PollOutcome(status="error", error_type="DecryptionError", error_message=str(exc))
    except FindHubError as exc:
        outcome = PollOutcome(status="error", error_type=type(exc).__name__, error_message=str(exc))
    except Exception as exc:
        log.exception("poll_unexpected_error", device=device_name)
        outcome = PollOutcome(status="error", error_type=type(exc).__name__, error_message=str(exc))
    else:
        if not observations:
            outcome = PollOutcome(status="no_location")
        else:
            with session_scope() as session:
                result = ingest_observations(session, observations, fetched_at=datetime.now(UTC))
            outcome = PollOutcome(
                status="ok",
                received=result.received,
                inserted=result.inserted,
                duplicates=result.duplicates,
            )

    outcome.device_id = device_id
    outcome.device_name = device_name

    with session_scope() as session:
        _record(session, device_id, started, outcome)

    _log_outcome(device_name, outcome, observations)
    return outcome


def poll_once(
    client: FindHubClient | None = None,
    settings: Settings | None = None,
    *,
    stagger_seconds: float | None = None,
    stop_event: threading.Event | None = None,
) -> CycleOutcome:
    """Poll every tracked device once, sequentially."""
    settings = settings or get_settings()
    client = client or FindHubClient(settings)
    stagger = DEVICE_STAGGER_SECONDS if stagger_seconds is None else stagger_seconds

    with session_scope() as session:
        targets = [(d.device_id, d.name) for d in get_tracked_devices(session)]

    if not targets:
        outcome = PollOutcome(
            status="error",
            error_type="NoDeviceTracked",
            error_message="No devices are being tracked. Run `findplus devices --track-all`.",
        )
        with session_scope() as session:
            _record(session, None, datetime.now(UTC), outcome)
        log.error("poll_no_devices_tracked")
        return CycleOutcome([outcome], config_error=True)

    cycle = CycleOutcome()
    for index, (device_id, device_name) in enumerate(targets):
        if stop_event is not None and stop_event.is_set():
            log.info("poll_cycle_interrupted", completed=index, total=len(targets))
            break
        if index and stagger:
            # Space requests out rather than firing N at once.
            if stop_event is not None:
                stop_event.wait(stagger)
            else:
                threading.Event().wait(stagger)
        cycle.outcomes.append(poll_device(device_id, device_name, client, settings))

    log.info(
        "poll_cycle_complete",
        devices=len(cycle.outcomes),
        new_observations=cycle.inserted,
        duplicates=cycle.duplicates,
        failures=sum(1 for o in cycle.outcomes if not o.ok),
    )
    return cycle


def _log_outcome(device_name: str, outcome: PollOutcome, observations=None) -> None:
    if outcome.status == "ok" and outcome.inserted:
        newest = max(o.observed_at for o in observations) if observations else None
        log.info(
            "poll successful",
            device=device_name,
            observed_at=newest.isoformat() if newest else None,
            new_observations=outcome.inserted,
            duplicates=outcome.duplicates,
        )
    elif outcome.status == "ok":
        log.info(
            "poll successful — same observation as previous, no new location saved",
            device=device_name,
            duplicates=outcome.duplicates,
        )
    elif outcome.status == "no_location":
        log.warning("poll successful — Find Hub returned no location", device=device_name)
    else:
        log.error(
            "poll failed",
            device=device_name,
            status=outcome.status,
            error_type=outcome.error_type,
            error=outcome.error_message,
        )


def _record(session, device_id: str | None, started: datetime, outcome: PollOutcome) -> None:
    finished = datetime.now(UTC)
    session.add(
        PollRun(
            device_id=device_id,
            started_at=started,
            finished_at=finished,
            status=outcome.status,
            observations_returned=outcome.received,
            observations_new=outcome.inserted,
            duration_ms=int((finished - started).total_seconds() * 1000),
            error_type=outcome.error_type,
            error_message=(outcome.error_message or "")[:2000] or None,
        )
    )


class PollerService:
    """Runs a poll cycle forever with backoff. Stoppable via `stop()`."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = FindHubClient(self.settings)
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
            cycle = poll_once(self.client, self.settings, stop_event=self._stop)
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
