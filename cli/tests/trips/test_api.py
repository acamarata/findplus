"""GET /api/trips: shape, labels, lock, validation, DST."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from findplus import honesty
from findplus.api import create_app
from findplus.db.session import session_scope
from findplus.ingest import ingest_observations, upsert_device
from tests.conftest import make_observation
from tests.trips._db import DEVICE, seed_school_day
from tests.trips._synth import HOME


@pytest.fixture
def client(tmp_db) -> TestClient:
    seed_school_day()
    return TestClient(create_app())


def _get(client: TestClient, **params):
    params = {"device_id": DEVICE, "date": "2026-09-18", "timezone": "UTC", **params}
    return client.get("/api/trips", params=params)


def test_trips_payload_carries_the_label(client: TestClient) -> None:
    body = _get(client).json()
    assert body["label"] == honesty.TRIPS_APPROXIMATE
    assert set(body) >= {"stays", "trips", "gaps", "label", "outliers", "fix_count"}


def test_school_day_shape_and_place_names(client: TestClient) -> None:
    body = _get(client).json()
    assert [s["label"] for s in body["stays"]] == ["Home", "School", "Home"]
    assert len(body["trips"]) == 2
    first = body["trips"][0]
    assert first["from"]["label"] == "Home" and first["to"]["label"] == "School"
    assert first["distance_approximate"] is True
    assert first["start_at"] == "2026-09-18T07:00:00Z"
    assert first["end_at"] == "2026-09-18T08:05:00Z"
    assert first["points"][0]["latitude"] and first["fix_count"] == 1
    assert body["stays"][0]["fix_count"] > 10  # noise collapsed into one row


def test_a_home_stay_with_jitter_does_not_leak_a_trip(client: TestClient) -> None:
    assert len(_get(client).json()["trips"]) == 2


def test_empty_day_is_empty_not_an_error(client: TestClient) -> None:
    body = _get(client, date="2026-09-01").json()
    assert body["stays"] == [] and body["trips"] == [] and body["gaps"] == []
    assert body["fix_count"] == 0 and body["first_fix_at"] is None


def test_unknown_device_404_and_bad_date_400(client: TestClient) -> None:
    assert _get(client, device_id="nope").status_code == 404
    assert _get(client, date="18/09/2026").status_code == 400
    assert client.get("/api/trips").status_code == 422  # device_id is required
    assert _get(client, days=99).status_code == 422


def test_days_spans_several_local_days(client: TestClient) -> None:
    body = _get(client, date="2026-09-17", days=2).json()
    assert body["days"] == 2 and len(body["stays"]) == 3


def test_locked_app_refuses_trips(client: TestClient) -> None:
    assert client.post("/api/settings/pin", json={"new_pin": "864213"}).status_code == 200
    client.cookies.clear()
    assert _get(client).status_code == 401
    assert (
        client.get("/api/trips/route", params={"device_id": DEVICE, "trip_id": "t1"}).status_code
        == 401
    )


def test_dst_spring_forward_day_in_new_york(tmp_db) -> None:
    """2026-03-08 is 23 hours long in New York; every fix still lands on that date."""
    start = datetime(2026, 3, 8, 5, 0, tzinfo=UTC)  # local midnight, UTC-5
    with session_scope() as session:
        upsert_device(session, DEVICE, "Tag")
        obs = [
            make_observation(
                device_id=DEVICE,
                device_name="Tag",
                lat=HOME[0],
                lon=HOME[1],
                observed_at=start + timedelta(minutes=30 * i),
                accuracy=40.0,
            )
            for i in range(46)  # last fix 03:30 UTC = 23:30 local EDT
        ]
        ingest_observations(session, obs, fetched_at=start + timedelta(days=2))
    client = TestClient(create_app())
    body = client.get(
        "/api/trips",
        params={"device_id": DEVICE, "date": "2026-03-08", "timezone": "America/New_York"},
    ).json()
    assert body["fix_count"] == 46 and len(body["stays"]) == 1 and body["trips"] == []
    stay = body["stays"][0]
    assert stay["start_local"].endswith("-05:00") and stay["start_local"].startswith(
        "2026-03-08T00:00"
    )
    assert stay["end_local"].endswith("-04:00")  # after the 2am jump
    assert stay["end_local"].startswith("2026-03-08T23:30")
    assert stay["duration_minutes"] == 22 * 60 + 30
    next_day = client.get(
        "/api/trips",
        params={"device_id": DEVICE, "date": "2026-03-09", "timezone": "America/New_York"},
    ).json()
    assert next_day["fix_count"] == 0
