"""Persistence of Find Hub observations, with deduplication.

Purpose : Turn a batch of `RawObservation`s into durable history without ever
          inventing a movement point.
Constraints:
    - The deduplication key is (device_id, observed_at, latitude_e7, longitude_e7).
      Google repeatedly returns the same last-known sighting; that is ONE
      observation, not one per poll. Re-seeing it bumps `times_returned` and
      `last_fetched_at` only.
    - Integer 1e-7 degrees make the comparison exact — no float tolerance games.
    - Raw data is never mutated or discarded. Movement filtering is a read-time
      concern (see `timeline.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from findplus.config import get_settings
from findplus.db.models import Device, LocationObservation, PlaceEvent
from findplus.findhub.types import RawObservation
from findplus.groups.events import evaluate_group_events as _group_events_evaluate
from findplus.logging_setup import get_logger
from findplus.places.events import evaluate as _geofence_evaluate

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Outcome of persisting one batch."""

    received: int
    inserted: int
    duplicates: int

    @property
    def summary(self) -> str:
        if self.received == 0:
            return "no observations returned"
        if self.inserted == 0:
            return (
                f"same observation as previous ({self.duplicates} duplicate(s)), nothing new saved"
            )
        return f"{self.inserted} new observation(s) saved, {self.duplicates} duplicate(s) skipped"


def upsert_device(
    session: Session,
    device_id: str,
    name: str,
    *,
    provider: str = "google-find-hub",
    now: datetime | None = None,
) -> Device:
    """Create or refresh a device row. Never changes the `is_tracked` flag.

    `provider` is set only when the row is first created — a device's provider
    is fixed at discovery time (which client/protocol it belongs to), so a
    later refresh (e.g. every successful poll calls this through
    `ingest_observations`) must never reassign it, or a device polled under
    one provider would flip back to the default on its very next poll.
    """
    now = now or datetime.now(UTC)
    device = session.get(Device, device_id)
    if device is None:
        device = Device(
            device_id=device_id,
            name=name,
            is_tracked=False,
            provider=provider,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(device)
    else:
        device.name = name or device.name
        device.last_seen_at = now
    session.flush()
    return device


def ingest_observations(
    session: Session,
    observations: list[RawObservation],
    *,
    fetched_at: datetime | None = None,
    settings: object | None = None,
) -> IngestResult:
    """Persist a batch, skipping sightings already on record.

    `fetched_at` is when THIS COMPUTER retrieved the batch, which is unrelated to
    `observed_at` — when Find Hub says the tag was actually seen. `settings`
    defaults to `get_settings()`; callers that already hold a Settings instance
    (poller.py) can pass it through instead of re-loading it here.
    """
    fetched_at = fetched_at or datetime.now(UTC)
    settings = settings or get_settings()
    if not observations:
        return IngestResult(received=0, inserted=0, duplicates=0)

    inserted = duplicates = 0
    # Collapse duplicates inside the batch itself before touching the DB.
    seen_in_batch: set[tuple] = set()
    new_rows: list[LocationObservation] = []

    for obs in observations:
        if obs.identity in seen_in_batch:
            duplicates += 1
            continue
        seen_in_batch.add(obs.identity)

        # provider is applied on INSERT only (see upsert_device): a device first
        # seen through a poll is tagged with the provider that reported it, and a
        # device already on record keeps the provider it was discovered under.
        upsert_device(
            session, obs.device_id, obs.device_name, provider=obs.provider, now=fetched_at
        )

        existing = session.scalar(
            select(LocationObservation).where(
                LocationObservation.device_id == obs.device_id,
                LocationObservation.observed_at == obs.observed_at,
                LocationObservation.latitude_e7 == obs.latitude_e7,
                LocationObservation.longitude_e7 == obs.longitude_e7,
            )
        )

        if existing is not None:
            # Identical sighting seen again: poll health, not movement.
            existing.times_returned += 1
            existing.last_fetched_at = fetched_at
            if existing.accuracy_meters is None and obs.accuracy_meters is not None:
                existing.accuracy_meters = obs.accuracy_meters
            if existing.battery_level is None and obs.battery_level is not None:
                existing.battery_level = obs.battery_level
            duplicates += 1
            continue

        lo = LocationObservation(
            device_id=obs.device_id,
            device_name=obs.device_name,
            latitude_e7=obs.latitude_e7,
            longitude_e7=obs.longitude_e7,
            altitude_meters=obs.altitude_meters,
            accuracy_meters=obs.accuracy_meters,
            observed_at=obs.observed_at,
            first_fetched_at=fetched_at,
            last_fetched_at=fetched_at,
            times_returned=1,
            source=obs.source,
            is_own_report=obs.is_own_report,
            semantic_name=obs.semantic_name,
            battery_level=obs.battery_level,
            raw_metadata=_encode_metadata(obs),
        )
        session.add(lo)
        new_rows.append(lo)
        inserted += 1

    session.flush()

    _run_post_ingest_hooks(session, new_rows, settings)

    result = IngestResult(received=len(observations), inserted=inserted, duplicates=duplicates)
    log.info(
        "ingest_complete",
        received=result.received,
        inserted=result.inserted,
        duplicates=result.duplicates,
    )
    return result


def _run_post_ingest_hooks(
    session: Session, new_rows: list[LocationObservation], settings: object
) -> None:
    """Run the per-observation hooks, never letting one lose the batch.

    The observations themselves are the irreplaceable data: a hook that raises
    (a bad place radius, a malformed group quorum, a bug in a downstream
    evaluator) must not roll back rows the provider will not hand us again, and
    must not break `poller.poll_device`'s "never raises on poll failure"
    contract. Each observation is guarded on its own so one bad fix does not
    skip the rest of the batch. The group-quorum hook runs in its own SAVEPOINT,
    after geofence's, so it can only see place_events geofence actually
    committed -- and a failure in it never rolls back the geofence hook's work.
    """
    for lo in sorted(new_rows, key=lambda o: o.observed_at):
        try:
            # SAVEPOINT: a DB-level failure inside the hook rolls back only the
            # hook's own writes, so the session stays usable and the
            # observations still commit.
            with session.begin_nested():
                _geofence_evaluate(
                    session,
                    lo,
                    default_accuracy=getattr(settings, "geofence_default_accuracy_meters", 100.0),
                )
        except Exception:
            log.exception(
                "post_ingest_hook_failed",
                hook="geofence",
                device=lo.device_id,
                observation_id=lo.id,
            )

        try:
            with session.begin_nested():
                _run_group_events_hook(session, lo, settings)
        except Exception:
            log.exception(
                "post_ingest_hook_failed",
                hook="group_events",
                device=lo.device_id,
                observation_id=lo.id,
            )


def _run_group_events_hook(session: Session, lo: LocationObservation, settings: object) -> None:
    """Evaluate group quorum for every place_event geofence just wrote for `lo`."""
    place_events = session.scalars(
        select(PlaceEvent).where(PlaceEvent.observation_id == lo.id)
    ).all()
    for place_event in place_events:
        _group_events_evaluate(session, place_event, settings)


def _encode_metadata(obs: RawObservation) -> str | None:
    import json

    if not obs.metadata:
        return None
    return json.dumps(obs.metadata, default=str, sort_keys=True)
