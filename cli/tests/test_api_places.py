"""/api/places: CRUD, events, presence, and the app lock."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from findplus.db.session import session_scope
from findplus.ingest import upsert_device


@pytest.fixture
def client(tmp_db):
    from findplus.api import create_app

    with session_scope() as session:
        upsert_device(session, "dev1", "Tag1")
    return TestClient(create_app())


def _create_body(**overrides) -> dict:
    body = {"name": "Home", "latitude": 41.1, "longitude": -80.64, "radius_meters": 100}
    body.update(overrides)
    return body


def test_list_empty(client: TestClient) -> None:
    assert client.get("/api/places").json() == []


def test_create(client: TestClient) -> None:
    res = client.post("/api/places", json=_create_body())
    assert res.status_code == 201
    body = res.json()
    assert "id" in body
    assert isinstance(body["latitude"], float)
    assert isinstance(body["longitude"], float)
    assert body["devices_inside"] == []


def test_create_timestamps_are_parseable_iso(client: TestClient) -> None:
    """Regression: UtcDateTime returns aware datetimes, so no trailing 'Z' is added."""
    body = client.post("/api/places", json=_create_body()).json()
    for field in ("created_at", "updated_at"):
        parsed = datetime.fromisoformat(body[field])
        assert parsed.tzinfo is not None


def test_create_duplicate(client: TestClient) -> None:
    client.post("/api/places", json=_create_body())
    res = client.post("/api/places", json=_create_body())
    assert res.status_code == 409


def test_create_radius_invalid(client: TestClient) -> None:
    res = client.post("/api/places", json=_create_body(radius_meters=10))
    assert res.status_code == 422


def test_list_after_create(client: TestClient) -> None:
    client.post("/api/places", json=_create_body())
    rows = client.get("/api/places").json()
    assert len(rows) == 1
    assert rows[0]["name"] == "Home"


def test_update_name(client: TestClient) -> None:
    place_id = client.post("/api/places", json=_create_body()).json()["id"]
    res = client.put(f"/api/places/{place_id}", json={"name": "Work"})
    assert res.status_code == 200
    assert res.json()["name"] == "Work"


def test_update_not_found(client: TestClient) -> None:
    assert client.put("/api/places/9999", json={"name": "X"}).status_code == 404


def test_delete(client: TestClient) -> None:
    place_id = client.post("/api/places", json=_create_body()).json()["id"]
    assert client.delete(f"/api/places/{place_id}").status_code == 204
    assert client.get("/api/places").json() == []


def test_delete_not_found(client: TestClient) -> None:
    assert client.delete("/api/places/9999").status_code == 404


def test_events_empty(client: TestClient) -> None:
    assert client.get("/api/places/events").json() == []


def test_presence_empty(client: TestClient) -> None:
    assert client.get("/api/places/presence").json() == []


def test_presence_matches_widget_and_group_default_window(client: TestClient) -> None:
    """UAT3 N17: the Places tab used to call a 70-minute-old fix stale (its
    own 60-minute default) while the widget and a fresh group's own default
    both called the same fix current at 90 minutes -- three surfaces giving
    three different answers about whether the same tracker was still nearby.
    Settings.presence_window_minutes (config.py) is now the one canonical
    default every one of them reads, so this is no longer stale at 70 minutes.
    """
    from datetime import UTC, datetime, timedelta

    from findplus.ingest import ingest_observations
    from findplus.places.repo import create_place
    from findplus.providers.google_findhub.types import RawObservation

    now = datetime.now(UTC)
    with session_scope() as session:
        create_place(
            session,
            name="Home",
            latitude_e7=411000000,
            longitude_e7=-806400000,
            radius_meters=200,
        )
    with session_scope() as session:
        ingest_observations(
            session,
            [
                RawObservation(
                    device_id="dev1",
                    device_name="Tag1",
                    latitude_e7=411000000,
                    longitude_e7=-806400000,
                    observed_at=now - timedelta(minutes=70),
                    accuracy_meters=15.0,
                    source="crowdsourced",
                    is_own_report=False,
                )
            ],
            fetched_at=now,
        )

    presence = client.get("/api/places/presence").json()
    assert presence[0]["stale"] is False
    assert presence[0]["state"] == "inside"
    assert client.get("/api/places").json()[0]["devices_inside"] == ["dev1"]


def test_locked(client: TestClient) -> None:
    client.post("/api/settings/pin", json={"new_pin": "864213"})
    client.cookies.clear()
    res = client.get("/api/places")
    assert res.status_code == 401
    assert res.json()["locked"] is True
