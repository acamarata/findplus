"""App settings (theme, idle timeout) and history-clear endpoints.

Split from test_lock_api.py (PRI rule 7, 449 lines); the gated-while-locked
case for /api/history/clear lives in test_lock_api_guards.py alongside the
rest of the locked-endpoint sweep. See _lock_helpers.py for the shared
client fixture.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from findplus.db.session import session_scope
from findplus.ingest import ingest_observations, upsert_device
from tests.api._lock_helpers import client, store  # noqa: F401
from tests.conftest import make_observation


# ----------------------------------------------------------------- settings
def test_theme_round_trips(client: TestClient) -> None:  # noqa: F811
    assert client.get("/api/settings").json()["theme"] == "dark"
    assert client.put("/api/settings", json={"theme": "light"}).json()["theme"] == "light"
    assert client.get("/api/settings").json()["theme"] == "light"


def test_unknown_theme_rejected(client: TestClient) -> None:  # noqa: F811
    assert client.put("/api/settings", json={"theme": "neon"}).status_code == 400


def test_idle_timeout_round_trips(client: TestClient) -> None:  # noqa: F811
    assert client.put("/api/settings", json={"idle_minutes": 5}).json()["idle_minutes"] == 5


def test_idle_timeout_zero_means_never(client: TestClient) -> None:  # noqa: F811
    assert client.put("/api/settings", json={"idle_minutes": 0}).json()["idle_minutes"] == 0


def test_absurd_idle_timeout_rejected(client: TestClient) -> None:  # noqa: F811
    assert client.put("/api/settings", json={"idle_minutes": 99999}).status_code == 400


# ---------------------------------------------------------- clear history
def test_clear_history_is_a_dry_run_without_confirmation(client: TestClient) -> None:  # noqa: F811
    body = client.post("/api/history/clear", json={}).json()
    assert body["deleted"] == 0
    assert body["would_delete"] == 2
    assert client.get("/api/status?timezone=UTC").json()["observations_total"] == 2


def test_clear_history_deletes_everything_when_confirmed(client: TestClient) -> None:  # noqa: F811
    body = client.post("/api/history/clear", json={"confirm": True}).json()
    assert body["deleted"] == 2
    assert client.get("/api/status?timezone=UTC").json()["observations_total"] == 0


def test_clear_history_can_target_one_device(client: TestClient) -> None:  # noqa: F811
    with session_scope() as session:
        upsert_device(session, "TAG-OTHER", "Keys")
        ingest_observations(
            session, [make_observation(device_id="TAG-OTHER", device_name="Keys", lat=42.0)]
        )
    body = client.post("/api/history/clear", json={"confirm": True, "device_id": "TAG-001"}).json()
    assert body["deleted"] == 2
    assert client.get("/api/status?timezone=UTC").json()["observations_total"] == 1


def test_history_clear_cascades_place_events(client: TestClient) -> None:  # noqa: F811
    """A place_event anchored to a cleared observation is deleted, not orphaned."""
    from sqlalchemy import func, select

    from findplus.db.models import LocationObservation, Place, PlaceEvent

    with session_scope() as session:
        obs = session.scalars(
            select(LocationObservation).order_by(LocationObservation.observed_at)
        ).first()
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

    body = client.post("/api/history/clear", json={"confirm": True}).json()
    assert body["deleted"] == 2

    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(PlaceEvent)) == 0
