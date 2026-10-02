"""GET /api/places/suggestions and the dismiss call, on the synthetic school-run family."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from findplus.api import create_app
from findplus.db.session import session_scope
from findplus.ingest import ingest_observations, upsert_device
from findplus.places.repo import create_place
from findplus.state import track_devices
from tests.conftest import make_observation
from tests.places._family import GRANDMA, HOME, SCHOOL, family_fixes

LAST_DAY = "2026-09-27"


def _seed() -> None:
    fixes = family_fixes()
    with session_scope() as s:
        for name in fixes:
            upsert_device(s, f"TAG-{name}", name, provider="test-fake")
        track_devices(s, [f"TAG-{n}" for n in fixes], exclusive=True)
        obs = [
            make_observation(
                device_id=f"TAG-{name}",
                device_name=name,
                lat=f.lat,
                lon=f.lon,
                observed_at=f.t,
                accuracy=f.accuracy_m,
            )
            for name, rows in fixes.items()
            for f in rows
        ]
        ingest_observations(s, obs, fetched_at=obs[-1].observed_at)


@pytest.fixture
def client(tmp_db) -> TestClient:
    _seed()
    return TestClient(create_app())


def _get(client: TestClient):
    return client.get("/api/places/suggestions", params={"timezone": "UTC", "date": LAST_DAY})


def test_shape_and_three_candidates(client: TestClient) -> None:
    body = _get(client).json()
    assert list(body) == ["candidates"] and len(body["candidates"]) == 3
    first = body["candidates"][0]
    assert first["kind_guess"] == "home" and first["trackers"] == ["Kai", "Mia"]
    assert abs(first["lat"] - HOME[0]) < 0.001
    assert {c["kind_guess"] for c in body["candidates"]} == {"home", "school_or_work", "regular"}
    points = [(c["lat"], c["lon"]) for c in body["candidates"]]
    for want in (HOME, SCHOOL, GRANDMA):
        assert any(abs(la - want[0]) < 0.002 and abs(lo - want[1]) < 0.002 for la, lo in points)


def test_a_saved_place_drops_out(client: TestClient) -> None:
    with session_scope() as s:
        create_place(
            s,
            name="Home",
            latitude_e7=round(HOME[0] * 1e7),
            longitude_e7=round(HOME[1] * 1e7),
            radius_meters=150,
            kind="home",
        )
    body = _get(client).json()
    assert len(body["candidates"]) == 2
    assert all(c["kind_guess"] != "home" for c in body["candidates"])


def test_not_a_place_is_remembered(client: TestClient) -> None:
    grandma = next(c for c in _get(client).json()["candidates"] if c["kind_guess"] == "regular")
    r = client.post(
        "/api/places/suggestions/dismiss",
        json={"latitude": grandma["lat"], "longitude": grandma["lon"]},
    )
    assert r.json() == {"dismissed": 1}
    kinds = [c["kind_guess"] for c in _get(client).json()["candidates"]]
    assert "regular" not in kinds and len(kinds) == 2


def test_empty_history_is_an_empty_list(tmp_db) -> None:
    assert _get(TestClient(create_app())).json() == {"candidates": []}


def test_dismiss_rejects_bad_coordinates(client: TestClient) -> None:
    r = client.post("/api/places/suggestions/dismiss", json={"latitude": 99, "longitude": 0})
    assert r.status_code == 422


def test_locked_app_refuses_suggestions(client: TestClient) -> None:
    assert client.post("/api/settings/pin", json={"new_pin": "864213"}).status_code == 200
    client.cookies.clear()
    assert _get(client).status_code == 401
    assert (
        client.post(
            "/api/places/suggestions/dismiss", json={"latitude": 1, "longitude": 1}
        ).status_code
        == 401
    )
