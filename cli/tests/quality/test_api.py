"""The stable read interface other packages import (quality/api.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from findplus.db.models import LocationObservation
from findplus.db.models_people import ObservationQuality
from findplus.ingest import upsert_device
from findplus.quality.api import is_suspect, suspect_ids

T0 = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


def _obs(session, device: str, minutes: int, *, suspect: bool | None) -> int:
    upsert_device(session, device, device)
    row = LocationObservation(
        device_id=device,
        device_name=device,
        latitude_e7=410000000 + minutes,
        longitude_e7=-800000000,
        observed_at=T0 + timedelta(minutes=minutes),
        first_fetched_at=T0,
        last_fetched_at=T0,
        times_returned=1,
    )
    session.add(row)
    session.flush()
    if suspect is not None:
        session.add(
            ObservationQuality(
                observation_id=row.id,
                score=0.2 if suspect else 1.0,
                suspect=suspect,
                reasons="aba_teleport" if suspect else "",
                algo_version=1,
                computed_at=T0,
            )
        )
        session.flush()
    return row.id


def test_suspect_ids_filters_by_device_and_window(session) -> None:
    bad = _obs(session, "d1", 5, suspect=True)
    _obs(session, "d1", 6, suspect=False)
    _obs(session, "d1", 7, suspect=None)
    _obs(session, "d2", 5, suspect=True)
    _obs(session, "d1", 90, suspect=True)
    got = suspect_ids(session, ["d1"], T0, T0 + timedelta(minutes=30))
    assert got == {bad}


def test_suspect_ids_empty_devices(session) -> None:
    assert suspect_ids(session, [], T0, T0 + timedelta(days=1)) == set()


def test_is_suspect(session) -> None:
    bad = _obs(session, "d1", 1, suspect=True)
    good = _obs(session, "d1", 2, suspect=False)
    none = _obs(session, "d1", 3, suspect=None)
    assert is_suspect(session, bad) is True
    assert is_suspect(session, good) is False
    assert is_suspect(session, none) is False
    assert is_suspect(session, 999999) is False
