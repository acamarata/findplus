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
from datetime import UTC, datetime

from findplus.config import Settings, get_settings
from findplus.db.session import session_scope
from findplus.findhub.types import (
    AuthRequiredError,
    DecryptionError,
    FindHubError,
    LocationTimeoutError,
)
from findplus.ingest import ingest_observations
from findplus.logging_setup import get_logger

# Re-exported so `from findplus.poller import PollOutcome` and existing
# monkeypatch targets keep resolving after the outcome types moved out.
from findplus.poller_outcomes import CycleOutcome as CycleOutcome
from findplus.poller_outcomes import PollOutcome as PollOutcome
from findplus.poller_outcomes import _log_outcome, _record
from findplus.providers.base import LocationProvider, get_provider
from findplus.state import get_tracked_devices

log = get_logger(__name__)

#: Seconds between consecutive device requests inside one cycle.
DEVICE_STAGGER_SECONDS = 10.0


def _resolve_provider(provider_name: str) -> tuple[LocationProvider | None, PollOutcome | None]:
    """Look the provider up and check it is usable. Returns (provider, failure).

    Every failure becomes a PollOutcome instead of an exception. A provider that
    is missing, half-installed (its entry point imports but the module it names
    does not), or whose availability probe throws must not kill the poll loop,
    and the attempt must still reach `poll_runs` through poll_device's tail.
    """
    try:
        provider = get_provider(provider_name)
    except KeyError as exc:
        return None, PollOutcome(
            status="provider_unavailable", error_type="unknown_provider", error_message=str(exc)
        )
    except Exception as exc:
        log.exception("provider_load_failed", provider=provider_name)
        return None, PollOutcome(
            status="provider_unavailable", error_type=type(exc).__name__, error_message=str(exc)
        )

    try:
        avail, reason = provider.is_available()
        if not avail:
            return None, PollOutcome(
                status="provider_unavailable", error_type="unavailable", error_message=reason
            )
        if not provider.is_authenticated():
            return None, PollOutcome(
                status="provider_unauthenticated",
                error_type="unauthenticated",
                error_message="provider not authenticated",
            )
    except Exception as exc:
        # A third-party provider's probe is not required to be total; ours is.
        log.exception("provider_probe_failed", provider=provider_name)
        return None, PollOutcome(
            status="provider_unavailable", error_type=type(exc).__name__, error_message=str(exc)
        )

    return provider, None


def _locate_and_ingest(
    provider: LocationProvider, device_id: str, device_name: str, settings: Settings
) -> tuple[PollOutcome, list | None]:
    """Ask the provider for fixes and persist them. Returns (outcome, observations)."""
    try:
        observations = provider.locate(device_id, device_name)
    except AuthRequiredError as exc:
        return PollOutcome(
            status="auth_error", error_type="AuthRequiredError", error_message=str(exc)
        ), None
    except LocationTimeoutError as exc:
        return PollOutcome(
            status="timeout", error_type="LocationTimeoutError", error_message=str(exc)
        ), None
    except DecryptionError as exc:
        return PollOutcome(
            status="error", error_type="DecryptionError", error_message=str(exc)
        ), None
    except FindHubError as exc:
        return PollOutcome(
            status="error", error_type=type(exc).__name__, error_message=str(exc)
        ), None
    except Exception as exc:
        log.exception("poll_unexpected_error", device=device_name)
        return PollOutcome(
            status="error", error_type=type(exc).__name__, error_message=str(exc)
        ), None

    if not observations:
        return PollOutcome(status="no_location"), observations

    with session_scope() as session:
        result = ingest_observations(
            session, observations, fetched_at=datetime.now(UTC), settings=settings
        )

    # Alert dispatch runs in its own session, after the ingest transaction has
    # already committed (dispatch.process() reads place_events/group_place_events
    # rows that ingest just wrote). Never let a dispatch failure crash the poller.
    try:
        with session_scope() as session:
            from findplus.alerts import dispatch as _alert_dispatch

            _alert_dispatch.process(_alert_dispatch.load_pending_events(session), session, settings)
    except Exception:
        log.exception("alert_dispatch_failed", device=device_name)

    return PollOutcome(
        status="ok",
        received=result.received,
        inserted=result.inserted,
        duplicates=result.duplicates,
    ), observations


def poll_device(
    device_id: str,
    device_name: str,
    provider_name: str = "google-find-hub",
    settings: Settings | None = None,
) -> PollOutcome:
    """Poll a single device and record the attempt. Never raises on poll failure."""
    settings = settings or get_settings()
    started = datetime.now(UTC)
    observations = None

    provider, outcome = _resolve_provider(provider_name)
    if provider is not None:
        outcome, observations = _locate_and_ingest(provider, device_id, device_name, settings)

    outcome.device_id = device_id
    outcome.device_name = device_name

    with session_scope() as session:
        _record(session, device_id, started, outcome)

    _log_outcome(device_name, outcome, observations)
    return outcome


def poll_once(
    settings: Settings | None = None,
    *,
    stagger_seconds: float | None = None,
    stop_event: threading.Event | None = None,
) -> CycleOutcome:
    """Poll every tracked device once, sequentially."""
    settings = settings or get_settings()
    stagger = DEVICE_STAGGER_SECONDS if stagger_seconds is None else stagger_seconds

    with session_scope() as session:
        targets = [(d.device_id, d.name, d.provider) for d in get_tracked_devices(session)]

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
    for index, (device_id, device_name, provider_name) in enumerate(targets):
        if stop_event is not None and stop_event.is_set():
            log.info("poll_cycle_interrupted", completed=index, total=len(targets))
            break
        if index and stagger:
            # Space requests out rather than firing N at once.
            if stop_event is not None:
                stop_event.wait(stagger)
            else:
                threading.Event().wait(stagger)
        cycle.outcomes.append(poll_device(device_id, device_name, provider_name, settings))

    log.info(
        "poll_cycle_complete",
        devices=len(cycle.outcomes),
        new_observations=cycle.inserted,
        duplicates=cycle.duplicates,
        failures=sum(1 for o in cycle.outcomes if not o.ok),
    )
    return cycle


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
