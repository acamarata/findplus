"""Timestamp storage: UTC canonical, aware round-trip, observed vs fetched."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from findplus.db.models import LocationObservation
from findplus.ingest import ingest_observations
from tests.conftest import make_observation


def test_timestamps_round_trip_as_aware_utc(session) -> None:
    observed = datetime(2026, 9, 18, 12, 2, 33, tzinfo=UTC)
    ingest_observations(session, [make_observation(observed_at=observed)])
    row = session.scalar(select(LocationObservation))
    assert row.observed_at.tzinfo is not None
    assert row.observed_at == observed


def test_non_utc_input_is_normalised_to_utc(session) -> None:
    """An observation given in a fixed offset stores the same instant."""
    eastern_time = datetime(2026, 9, 18, 8, 2, 33, tzinfo=timezone(timedelta(hours=-4)))
    ingest_observations(session, [make_observation(observed_at=eastern_time)])
    row = session.scalar(select(LocationObservation))
    assert row.observed_at == datetime(2026, 9, 18, 12, 2, 33, tzinfo=UTC)


def test_naive_datetimes_are_rejected() -> None:
    """Storing a naive datetime would silently corrupt day grouping."""
    from findplus.db.types import UtcDateTime

    with pytest.raises(ValueError, match="naive datetime"):
        UtcDateTime().process_bind_param(datetime(2026, 9, 18, 12, 0), None)


def test_observed_and_fetched_are_independent(session) -> None:
    """Find Hub sighting time and our retrieval time are not the same thing."""
    observed = datetime(2026, 9, 18, 16, 43, 0, tzinfo=UTC)
    fetched = datetime(2026, 9, 18, 16, 46, 12, tzinfo=UTC)
    ingest_observations(session, [make_observation(observed_at=observed)], fetched_at=fetched)

    row = session.scalar(select(LocationObservation))
    assert row.observed_at == observed
    assert row.first_fetched_at == fetched
    assert (row.first_fetched_at - row.observed_at).total_seconds() == pytest.approx(192)


def test_local_conversion_matches_the_wall_clock(session) -> None:
    eastern = ZoneInfo("America/New_York")
    ingest_observations(
        session, [make_observation(observed_at=datetime(2026, 9, 18, 12, 2, 33, tzinfo=UTC))]
    )
    row = session.scalar(select(LocationObservation))
    local = row.observed_at.astimezone(eastern)
    assert (local.hour, local.minute) == (8, 2)  # 12:02 UTC = 08:02 EDT


def test_coordinates_round_trip_at_full_precision(session) -> None:
    ingest_observations(session, [make_observation(lat=41.1234567, lon=-80.7654321)])
    row = session.scalar(select(LocationObservation))
    assert row.latitude_e7 == 411234567
    assert row.longitude_e7 == -807654321
    assert row.latitude == pytest.approx(41.1234567)
    assert row.longitude == pytest.approx(-80.7654321)
