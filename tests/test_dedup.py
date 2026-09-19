"""Deduplication: Google repeating a sighting must not create movement."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from bike_tracker.db.models import LocationObservation
from bike_tracker.ingest import ingest_observations
from tests.conftest import make_observation


def _count(session) -> int:
    return int(session.scalar(select(func.count(LocationObservation.id))) or 0)


def test_first_batch_is_inserted(session) -> None:
    result = ingest_observations(session, [make_observation(minutes=0)])
    assert (result.received, result.inserted, result.duplicates) == (1, 1, 0)
    assert _count(session) == 1


def test_identical_sighting_returned_again_is_not_a_new_point(session) -> None:
    """The core requirement: polling every 5 minutes must not fabricate movement."""
    obs = make_observation(minutes=0)
    ingest_observations(session, [obs], fetched_at=datetime(2026, 9, 18, 12, 1, tzinfo=UTC))

    for extra in range(1, 6):  # five more polls returning the same last-known fix
        result = ingest_observations(
            session, [obs], fetched_at=datetime(2026, 9, 18, 12, 1 + 5 * extra, tzinfo=UTC)
        )
        assert result.inserted == 0
        assert result.duplicates == 1

    assert _count(session) == 1
    row = session.scalar(select(LocationObservation))
    assert row.times_returned == 6, "repeat sightings must be counted, not stored as points"


def test_repeat_updates_last_fetched_but_not_first(session) -> None:
    obs = make_observation(minutes=0)
    first_fetch = datetime(2026, 9, 18, 12, 1, tzinfo=UTC)
    later_fetch = datetime(2026, 9, 18, 12, 31, tzinfo=UTC)
    ingest_observations(session, [obs], fetched_at=first_fetch)
    ingest_observations(session, [obs], fetched_at=later_fetch)

    row = session.scalar(select(LocationObservation))
    assert row.first_fetched_at == first_fetch
    assert row.last_fetched_at == later_fetch


def test_different_timestamp_same_place_is_a_distinct_observation(session) -> None:
    """A tag seen again later at the same spot is a real new sighting."""
    ingest_observations(session, [make_observation(minutes=0)])
    result = ingest_observations(session, [make_observation(minutes=17)])
    assert result.inserted == 1
    assert _count(session) == 2


def test_same_timestamp_different_place_is_distinct(session) -> None:
    ingest_observations(session, [make_observation(minutes=0, lat=41.10)])
    result = ingest_observations(session, [make_observation(minutes=0, lat=41.20)])
    assert result.inserted == 1
    assert _count(session) == 2


def test_duplicates_within_a_single_batch_are_collapsed(session) -> None:
    obs = make_observation(minutes=0)
    result = ingest_observations(session, [obs, obs, obs])
    assert result.received == 3
    assert result.inserted == 1
    assert result.duplicates == 2
    assert _count(session) == 1


def test_multi_report_batch_inserts_every_distinct_sighting(session) -> None:
    """One poll commonly returns several timestamped reports; all must be kept."""
    batch = [make_observation(minutes=m, lat=41.10 + m / 1000) for m in (0, 7, 19, 33)]
    result = ingest_observations(session, batch)
    assert result.inserted == 4
    assert _count(session) == 4


def test_sub_meter_coordinate_change_is_still_a_distinct_row(session) -> None:
    """Dedup is exact on 1e-7 degrees; it does not silently merge nearby fixes."""
    ingest_observations(session, [make_observation(minutes=0, lat=41.1234560)])
    result = ingest_observations(session, [make_observation(minutes=0, lat=41.1234561)])
    assert result.inserted == 1


def test_empty_batch_is_harmless(session) -> None:
    result = ingest_observations(session, [])
    assert (result.received, result.inserted, result.duplicates) == (0, 0, 0)
    assert "no observations" in result.summary


def test_device_row_is_created_and_refreshed(session) -> None:
    from bike_tracker.db.models import Device

    ingest_observations(session, [make_observation(minutes=0)])
    device = session.get(Device, "TAG-001")
    assert device is not None
    assert device.name == "Moto Tag 2"

    later = datetime(2026, 9, 18, 14, 0, tzinfo=UTC) + timedelta(hours=1)
    ingest_observations(session, [make_observation(minutes=120)], fetched_at=later)
    session.refresh(device)
    assert device.last_seen_at == later
