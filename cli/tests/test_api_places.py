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


def test_locked(client: TestClient) -> None:
    client.post("/api/settings/pin", json={"new_pin": "864213"})
    client.cookies.clear()
    res = client.get("/api/places")
    assert res.status_code == 401
    assert res.json()["locked"] is True
