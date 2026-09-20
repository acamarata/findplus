"""The whole native chain: rule -> event -> dispatch -> deliveries -> ack.

Purpose    : Every earlier test stops at one seam. This drives the real route
             surface end to end so a contract break between dispatch and the
             poller's two endpoints cannot hide between two green unit tests.
Constraints: No poller thread and no socket -- dispatch.process runs in
             process against the same database the TestClient serves.
"""

from __future__ import annotations

import datetime

import pytest
from fastapi.testclient import TestClient

from findplus.alerts import dispatch
from findplus.config import get_settings
from findplus.db.models import Device, LocationObservation, Place, PlaceEvent
from findplus.db.session import session_scope

NOW = datetime.datetime(2026, 9, 20, 12, 0, 0, tzinfo=datetime.UTC)


@pytest.fixture
def client(tmp_db):
    from findplus.api import create_app

    with session_scope() as s:
        s.add(
            Place(
                id=1,
                name="Home",
                latitude_e7=0,
                longitude_e7=0,
                radius_meters=100,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        s.add(
            Device(
                device_id="dev1",
                name="Tag",
                is_tracked=True,
                first_seen_at=NOW,
                last_seen_at=NOW,
            )
        )
    return TestClient(create_app())


def _seed_unnotified_crossing() -> None:
    """A place_events row with notified_at NULL: the ingest hand-off dispatch reads."""
    with session_scope() as s:
        obs = LocationObservation(
            device_id="dev1",
            device_name="Tag",
            latitude_e7=0,
            longitude_e7=0,
            observed_at=NOW,
            first_fetched_at=NOW,
            last_fetched_at=NOW,
            times_returned=1,
        )
        s.add(obs)
        s.flush()
        s.add(
            PlaceEvent(
                place_id=1,
                device_id="dev1",
                event_type="ENTER",
                observed_at=NOW,
                fetched_at=NOW,
                observation_id=obs.id,
                confidence="high",
                distance_meters=10.0,
                notified_at=None,
            )
        )


def _dispatch_once() -> None:
    with session_scope() as s:
        dispatch.process(dispatch.load_pending_events(s), s, get_settings(), now=NOW)


def _create_native_rule(client: TestClient) -> int:
    res = client.post(
        "/api/alerts/rules",
        json={"name": "native rule", "place_id": 1, "device_id": "dev1", "channels": ["native"]},
    )
    assert res.status_code == 201, res.text
    assert res.json()["channels"] == ["native"]
    return res.json()["id"]


def test_the_queue_carries_a_rendered_alert_the_poller_can_show(client: TestClient) -> None:
    _create_native_rule(client)
    _seed_unnotified_crossing()
    _dispatch_once()
    rows = client.get("/api/alerts/deliveries?channel=native").json()
    assert len(rows) == 1
    assert rows[0]["status"] == "queued"
    assert rows[0]["text"] == "Tag arrived at Home"
    assert rows[0]["body"]


def test_ack_closes_the_row_and_the_cursor_moves_past_it(client: TestClient) -> None:
    _create_native_rule(client)
    _seed_unnotified_crossing()
    _dispatch_once()
    delivery_id = client.get("/api/alerts/deliveries?channel=native").json()[0]["id"]

    assert client.post(f"/api/alerts/deliveries/{delivery_id}/ack").status_code == 204
    acked = client.get("/api/alerts/deliveries?channel=native").json()[0]
    assert acked["status"] == "delivered"
    assert acked["delivered_at"]
    assert client.get(f"/api/alerts/deliveries?since={delivery_id}&channel=native").json() == []


def test_a_retried_ack_is_404_not_a_conflict(client: TestClient) -> None:
    _create_native_rule(client)
    _seed_unnotified_crossing()
    _dispatch_once()
    delivery_id = client.get("/api/alerts/deliveries?channel=native").json()[0]["id"]
    client.post(f"/api/alerts/deliveries/{delivery_id}/ack")
    assert client.post(f"/api/alerts/deliveries/{delivery_id}/ack").status_code == 404


def test_a_second_dispatch_of_the_same_event_adds_no_second_row(client: TestClient) -> None:
    """The widened UNIQUE plus _deliver_one's dedup SELECT, through the real routes."""
    _create_native_rule(client)
    _seed_unnotified_crossing()
    _dispatch_once()
    with session_scope() as s:
        s.execute(PlaceEvent.__table__.update().values(notified_at=None))
    _dispatch_once()
    assert len(client.get("/api/alerts/deliveries?channel=native").json()) == 1
