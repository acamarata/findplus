"""The polling service.

Purpose : Query Find Hub on a schedule, persist new observations, record health.
Constraints:
    - A failed poll NEVER crashes the daemon. Every outcome is written to
      `poll_runs`, including the failure class and message.
    - Consecutive failures apply exponential backoff, capped by
      `poll_max_backoff_minutes`. Success resets the backoff.
    - A missed wake-up (laptop asleep) is not an error: the loop measures elapsed
      wall-clock and simply polls at the next opportunity.
    - Locations are never fabricated. A poll that returns nothing records
      `status="no_location"` and stores no coordinates.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime

from bike_tracker.config import Settings, get_settings
from bike_tracker.db.models import PollRun
from bike_tracker.db.session import session_scope
from bike_tracker.findhub.client import FindHubClient
from bike_tracker.findhub.types import (
    AuthRequiredError,
    DecryptionError,
    FindHubError,
    LocationTimeoutError,
)
from bike_tracker.ingest import ingest_observations
from bike_tracker.logging_setup import get_logger
from bike_tracker.state import get_selected_device

log = get_logger(__name__)


@dataclass(slots=True)
class PollOutcome:
    status: str
    received: int = 0
    inserted: int = 0
    duplicates: int = 0
    error_type: str | None = None
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in {"ok", "no_location"}


def poll_once(client: FindHubClient | None = None, settings: Settings | None = None) -> PollOutcome:
    """Execute exactly one poll cycle and record it. Never raises on poll failure."""
    settings = settings or get_settings()
    client = client or FindHubClient(settings)
    started = datetime.now(UTC)

    with session_scope() as session:
        device = get_selected_device(session)
        if device is None:
            outcome = PollOutcome(
                status="error",
                error_type="NoDeviceSelected",
                error_message=("No tracker selected. Run `bike-tracker devices --select <id>`."),
            )
            _record(session, None, started, outcome)
            log.error("poll_no_device_selected")
            return outcome

        device_id, device_name = device.device_id, device.name

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
        log.exception("poll_unexpected_error")
        outcome = PollOutcome(status="error", error_type=type(exc).__name__, error_message=str(exc))
    else:
        if not observations:
            outcome = PollOutcome(status="no_location", received=0)
        else:
            with session_scope() as session:
                result = ingest_observations(session, observations, fetched_at=datetime.now(UTC))
            outcome = PollOutcome(
                status="ok",
                received=result.received,
                inserted=result.inserted,
                duplicates=result.duplicates,
            )

    with session_scope() as session:
        _record(session, device_id, started, outcome)

    _log_outcome(device_name, outcome, observations=locals().get("observations"))
    return outcome


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
    """Runs `poll_once` forever with backoff. Stoppable via `stop()`."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = FindHubClient(self.settings)
        self._stop = threading.Event()
        self._consecutive_failures = 0
        self.last_outcome: PollOutcome | None = None

    def stop(self) -> None:
        self._stop.set()

    def _next_delay_seconds(self) -> float:
        base = self.settings.effective_poll_interval_minutes * 60.0
        if self._consecutive_failures == 0:
            return base
        # 2x, 4x, 8x ... capped.
        backoff = base * (2 ** min(self._consecutive_failures, 6))
        return min(backoff, self.settings.poll_max_backoff_minutes * 60.0)

    def run_forever(self) -> None:
        interval = self.settings.effective_poll_interval_minutes
        if self.settings.allow_fast_polling and self.settings.poll_interval_minutes < 5:
            log.warning(
                "fast_polling_enabled",
                interval_minutes=interval,
                note="Polling faster than 5 minutes risks Google rate-limiting "
                "or account flags. This was explicitly opted into.",
            )
        log.info("poller_started", interval_minutes=interval, pid=_pid())

        while not self._stop.is_set():
            outcome = poll_once(self.client, self.settings)
            self.last_outcome = outcome
            if outcome.ok:
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
            # Event.wait() returns early on stop(); it also tolerates system sleep,
            # after which the next iteration simply runs late rather than failing.
            self._stop.wait(delay)

        log.info("poller_stopped")


def _pid() -> int:
    import os

    return os.getpid()
