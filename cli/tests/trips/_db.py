"""DB seeding for the trips API/CLI/MCP tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from findplus.db.session import session_scope
from findplus.ingest import ingest_observations, upsert_device
from findplus.places.repo import create_place
from findplus.state import track_devices
from tests.conftest import make_observation
from tests.trips._synth import HOME, SCHOOL, offset

DEVICE = "TAG-SON"


def seed_school_day(
    day_utc: datetime = datetime(2026, 9, 18, 0, 0, tzinfo=UTC), name: str = "Son's Tag"
) -> None:
    """Home, a school run, school, the run back, home; plus Home and School places."""
    plan: list[tuple[float, tuple[float, float], float]] = []
    for m in range(0, 7 * 60 + 1, 20):
        plan.append((m, offset(HOME, (m % 40) - 20, 0), 60.0))
    plan.append((7 * 60 + 40, offset(HOME, 1400, 1000), 100.0))
    for m in range(8 * 60 + 5, 15 * 60 + 1, 30):
        plan.append((m, SCHOOL, 60.0))
    plan.append((15 * 60 + 25, offset(HOME, 1400, 1000), 100.0))
    for m in range(15 * 60 + 50, 23 * 60 + 1, 30):
        plan.append((m, HOME, 60.0))
    with session_scope() as session:
        upsert_device(session, DEVICE, name, provider="test-fake")
        track_devices(session, [DEVICE], exclusive=True)
        for label, pt in (("Home", HOME), ("School", SCHOOL)):
            create_place(
                session,
                name=label,
                latitude_e7=round(pt[0] * 1e7),
                longitude_e7=round(pt[1] * 1e7),
                radius_meters=200,
            )
        obs = [
            make_observation(
                device_id=DEVICE,
                device_name=name,
                lat=lat,
                lon=lon,
                observed_at=day_utc + timedelta(minutes=m),
                accuracy=acc,
            )
            for m, (lat, lon), acc in plan
        ]
        ingest_observations(session, obs, fetched_at=day_utc + timedelta(days=1))
