"""Daily retention job: prunes location history, place events and group-place events.

Purpose    : Unattended deletion of old rows so history.retention_days actually
             shrinks the database.
Inputs     : Settings.retention_days, re-read fresh every run (not held from
             construction, unlike PollerService), so an API-driven change
             applies on the next cycle with no daemon restart.
Outputs    : A RetentionResult per run, and a retention_pruned log line.
Constraints: Deletes ONLY location_observations, place_events and
             group_place_events -- never devices, places, groups,
             device_groups, place_states or any alert table, which are
             configuration and current state, not history.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from findplus.config import get_settings
from findplus.db.models import GroupPlaceEvent, LocationObservation, PlaceEvent
from findplus.db.session import session_scope
from findplus.logging_setup import get_logger

log = get_logger(__name__)

#: Re-run cadence: once a day. Not a Settings field (nothing needs to tune it).
RUN_INTERVAL_SECONDS = 24 * 60 * 60

#: The three history tables, in prune order: the events first, because
#: place_events.observation_id is ON DELETE CASCADE, so pruning observations
#: first would silently take their events with it and under-report the count.
#: Anything absent from this tuple is configuration or current state, and stays.
_HISTORY_TABLES = (PlaceEvent, GroupPlaceEvent, LocationObservation)


@dataclass(frozen=True, slots=True)
class RetentionResult:
    ran: bool
    cutoff: datetime | None
    observations_deleted: int
    place_events_deleted: int
    group_place_events_deleted: int


#: What a run returns when retention is off (retention_days <= 0 = keep forever).
_DISABLED = RetentionResult(False, None, 0, 0, 0)


def run_once(state_dir: Path | None = None) -> RetentionResult:
    """Prune every history row older than the configured window.

    Settings are read here, not by the caller, so a retention change made
    through PATCH /api/settings applies on the very next run.
    """
    settings = get_settings(state_dir)
    if settings.retention_days <= 0:
        return _DISABLED

    cutoff = datetime.now(UTC) - timedelta(days=settings.retention_days)
    # One transaction for all three: a crash must not orphan a place event.
    with session_scope() as session:
        place_events, group_events, observations = [
            session.query(model)
            .filter(model.observed_at < cutoff)
            .delete(synchronize_session=False)
            for model in _HISTORY_TABLES
        ]

    log.info(
        "retention_pruned",
        cutoff=cutoff.isoformat(),
        observations_deleted=observations,
        place_events_deleted=place_events,
        group_place_events_deleted=group_events,
    )
    return RetentionResult(
        ran=True,
        cutoff=cutoff,
        observations_deleted=observations,
        place_events_deleted=place_events,
        group_place_events_deleted=group_events,
    )


class RetentionScheduler:
    """Runs run_once() at once, then every RUN_INTERVAL_SECONDS until stop()."""

    def __init__(self, state_dir: Path | None = None) -> None:
        self._state_dir = state_dir
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run_forever(self) -> None:
        log.info("retention_scheduler_started")
        while not self._stop.is_set():
            run_once(self._state_dir)
            self._stop.wait(RUN_INTERVAL_SECONDS)
        log.info("retention_scheduler_stopped")
