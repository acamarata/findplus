"""Poll results: the per-device and per-cycle outcome types, and how they are recorded.

Purpose : Describe what one poll attempt produced, write it to `poll_runs`, and
          render it as a log line. Split out of `poller.py` so that module stays
          inside the 300-line file budget (PRI hard rule 7).
Inputs  : PollOutcome values produced by `poller.poll_device`.
Outputs : `poll_runs` rows; structured log lines.
Constraints:
    - No provider, network or settings imports: this module only describes and
      records results, it never performs a poll.
    - Re-exported by `findplus.poller`, so `from findplus.poller import
      PollOutcome` and `monkeypatch.setattr("findplus.poller._record", ...)`
      keep resolving exactly as before the split.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from findplus.db.models import PollRun
from findplus.db.session import session_scope
from findplus.logging_setup import get_logger

log = get_logger(__name__)


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
        # provider_unavailable/provider_unauthenticated are environment state, not
        # a provider-network failure — same precedent as config_error on
        # CycleOutcome below — so neither escalates the cycle backoff.
        return self.status in {
            "ok",
            "no_location",
            "provider_unavailable",
            "provider_unauthenticated",
        }


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


def record_config_error_cycle(
    error_type: str, message: str, log_event: str, *, config_error: bool = False, **log_extra
) -> CycleOutcome:
    """Build, record and log a single-outcome cycle for a pre-poll configuration failure.

    Shared by `poll_once`'s "nothing tracked" and "unknown --device-id" cases —
    neither ever reaches `poll_device`, so there is no per-device outcome to
    build from a real attempt. Lives here, not in poller.py, to keep that
    module inside the 300-line file budget (see this module's own docstring).
    """
    outcome = PollOutcome(status="error", error_type=error_type, error_message=message)
    with session_scope() as session:
        _record(session, None, datetime.now(UTC), outcome)
    log.error(log_event, **log_extra)
    return CycleOutcome([outcome], config_error=config_error)
