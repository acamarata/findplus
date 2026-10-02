"""POST /api/alerts/rules/dry-run: what a rule would have sent in the last day."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from findplus.db.session import session_scope
from findplus.ingest import ingest_observations, upsert_device
from findplus.places.repo import create_place
from findplus.providers.google_findhub.types import RawObservation

LAT = 41.1


def _obs(device_id: str, lat: float, minutes_ago: int) -> RawObservation:
    return RawObservation(
        device_id=device_id,
        device_name="Sam Bag",
        latitude_e7=round(lat * 1e7),
        longitude_e7=round(-80.1 * 1e7),
        observed_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
        accuracy_meters=15.0,
        source="crowdsourced",
        is_own_report=False,
    )


@pytest.fixture
def client(tmp_db):
    from findplus.api import create_app

    with session_scope() as s:
        upsert_device(s, "bag", "Sam Bag")
        upsert_device(s, "other", "Other Tag")
    with session_scope() as s:
        create_place(
            s,
            name="School",
            latitude_e7=round(LAT * 1e7),
            longitude_e7=round(-80.1 * 1e7),
            radius_meters=200,
            color="#3b82f6",
            enter_confirmations=1,
            exit_confirmations=1,
        )
    # outside, arrives, leaves again: one ENTER and one EXIT, 100 minutes apart
    with session_scope() as s:
        ingest_observations(
            s,
            [_obs("bag", LAT + 0.01, 300), _obs("bag", LAT, 200), _obs("bag", LAT + 0.01, 100)],
            fetched_at=datetime.now(UTC),
        )
    return TestClient(create_app())


def _body(**over):
    body = {"device_id": "bag", "on_enter": True, "on_exit": True, "cooldown_minutes": 30}
    return {**body, **over}


def test_lists_the_arrival_and_the_departure_in_order(client: TestClient) -> None:
    res = client.post("/api/alerts/rules/dry-run", json=_body())
    assert res.status_code == 200
    data = res.json()
    assert [r["text"] for r in data["rows"]] == [
        "Sam Bag arrived at School",
        "Sam Bag left School",
    ]
    assert data["would_send"] == 2 and data["held_back"] == 0
    assert data["window_hours"] == 24


def test_only_the_events_the_rule_asks_for(client: TestClient) -> None:
    rows = client.post("/api/alerts/rules/dry-run", json=_body(on_enter=False)).json()["rows"]
    assert [r["event_type"] for r in rows] == ["EXIT"]


def test_cooldown_holds_the_second_message_back(client: TestClient) -> None:
    data = client.post("/api/alerts/rules/dry-run", json=_body(cooldown_minutes=1000)).json()
    assert [r["sends"] for r in data["rows"]] == [True, False]
    assert data["would_send"] == 1 and data["held_back"] == 1


def test_another_tracker_matches_nothing(client: TestClient) -> None:
    data = client.post("/api/alerts/rules/dry-run", json=_body(device_id="other")).json()
    assert data["rows"] == [] and data["would_send"] == 0


def test_window_can_be_shortened(client: TestClient) -> None:
    # Only the 100-minutes-ago departure is inside a 3 hour window.
    rows = client.post("/api/alerts/rules/dry-run", json=_body(hours=3)).json()["rows"]
    assert [r["event_type"] for r in rows] == ["EXIT"]


def test_needs_exactly_one_target(client: TestClient) -> None:
    assert client.post("/api/alerts/rules/dry-run", json={}).status_code == 422
    both = _body(group_id=1)
    assert client.post("/api/alerts/rules/dry-run", json=both).status_code == 422


def test_reads_only(client: TestClient) -> None:
    client.post("/api/alerts/rules/dry-run", json=_body())
    assert client.get("/api/alerts/deliveries").json() == []
