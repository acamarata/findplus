"""`findplus prune` cascades place_events anchored to the pruned observation."""

from __future__ import annotations

from datetime import UTC, datetime

from click.testing import CliRunner
from sqlalchemy import func, select

from findplus.cli.main import main
from findplus.db.models import LocationObservation, Place, PlaceEvent
from findplus.db.session import session_scope
from findplus.ingest import ingest_observations, upsert_device
from tests.conftest import make_observation


def test_prune_cascades_place_events(tmp_db: str) -> None:
    with session_scope() as session:
        upsert_device(session, "TAG-001", "Moto Tag 2")
        ingest_observations(session, [make_observation(minutes=0)])
        obs = session.scalars(select(LocationObservation)).first()
        place = Place(
            name="P1",
            latitude_e7=411000000,
            longitude_e7=-806400000,
            radius_meters=100,
            color="#2f80ed",
            enter_confirmations=1,
            exit_confirmations=2,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(place)
        session.flush()
        session.add(
            PlaceEvent(
                place_id=place.id,
                device_id="TAG-001",
                event_type="ENTER",
                observed_at=obs.observed_at,
                fetched_at=obs.last_fetched_at,
                observation_id=obs.id,
                confidence="high",
                distance_meters=42.0,
            )
        )

    result = CliRunner().invoke(main, ["prune", "--before", "2026-09-19", "--yes"], input="y\n")
    assert result.exit_code == 0, result.output

    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(PlaceEvent)) == 0
