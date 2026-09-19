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

from findplus.db.models import Device, LocationObservation
from findplus.findhub.types import RawObservation
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
) -> IngestResult:
    """Persist a batch, skipping sightings already on record.

    `fetched_at` is when THIS COMPUTER retrieved the batch, which is unrelated to
    `observed_at` — when Find Hub says the tag was actually seen.
    """
    fetched_at = fetched_at or datetime.now(UTC)
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

    for lo in sorted(new_rows, key=lambda o: o.observed_at):
        _geofence_evaluate(session, lo)

    result = IngestResult(received=len(observations), inserted=inserted, duplicates=duplicates)
    log.info(
        "ingest_complete",
        received=result.received,
        inserted=result.inserted,
        duplicates=result.duplicates,
    )
    return result


def _encode_metadata(obs: RawObservation) -> str | None:
    import json

    if not obs.metadata:
        return None
    return json.dumps(obs.metadata, default=str, sort_keys=True)
