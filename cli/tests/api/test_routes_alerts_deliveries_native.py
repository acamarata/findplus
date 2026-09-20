"""GET /api/alerts/deliveries (since/channel/text/body) and POST .../{id}/ack.

Purpose : Pin the queue contract the desktop native poller drains -- the cursor,
          the channel filter, the rendered text, the ack's 204-then-404, and the
          401 a locked session gets from both routes.
"""

from __future__ import annotations

import datetime

import pytest
from fastapi.testclient import TestClient

from findplus.db.models import Device, LocationObservation, Place, PlaceEvent
from findplus.db.models_alerts import AlertDelivery, AlertRule
from findplus.db.session import session_scope

NOW = datetime.datetime(2026, 9, 20, 12, 0, 0, tzinfo=datetime.UTC)


@pytest.fixture
def client(tmp_db):
    from findplus.api import create_app

    return TestClient(create_app())


def _seed(place_event: bool = True) -> tuple[int, int]:
    """One rule plus one place_event; returns (rule_id, place_event_id)."""
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
        s.flush()
        rule = AlertRule(
            name="native rule",
            place_id=1,
            device_id="dev1",
            on_enter=True,
            on_exit=True,
            channels="native",
            cooldown_minutes=30,
            enabled=True,
            also_notify_members=False,
            created_at=NOW,
        )
        s.add(rule)
        event_id = 0
        if place_event:
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
            event = PlaceEvent(
                place_id=1,
                device_id="dev1",
                event_type="ENTER",
                observed_at=NOW,
                fetched_at=NOW,
                observation_id=obs.id,
                confidence="high",
                distance_meters=10.0,
            )
            s.add(event)
            s.flush()
            event_id = event.id
        s.commit()
        return rule.id, event_id


def _add_delivery(rule_id: int, event_id: int, channel: str, status: str = "queued") -> int:
    with session_scope() as s:
        row = AlertDelivery(
            rule_id=rule_id,
            event_kind="device",
            event_id=event_id,
            channel=channel,
            sent_at=NOW,
            status=status,
        )
        s.add(row)
        s.commit()
        return row.id


def test_channel_filter_returns_only_that_channel(client: TestClient) -> None:
    rule_id, event_id = _seed()
    _add_delivery(rule_id, event_id, "native")
    _add_delivery(rule_id, event_id, "telegram", status="sent")
    rows = client.get("/api/alerts/deliveries?channel=native").json()
    assert [r["channel"] for r in rows] == ["native"]


def test_since_is_an_exclusive_ascending_cursor(client: TestClient) -> None:
    rule_id, event_id = _seed()
    first = _add_delivery(rule_id, event_id, "native")
    second = _add_delivery(rule_id, event_id + 1, "native")
    third = _add_delivery(rule_id, event_id + 2, "native")
    rows = client.get(f"/api/alerts/deliveries?since={first}&channel=native").json()
    assert [r["id"] for r in rows] == [second, third]
    assert client.get(f"/api/alerts/deliveries?since={third}").json() == []


def test_a_native_row_carries_the_rendered_text_and_body(client: TestClient) -> None:
    rule_id, event_id = _seed()
    _add_delivery(rule_id, event_id, "native")
    row = client.get("/api/alerts/deliveries?channel=native").json()[0]
    assert row["text"] == "Tag arrived at Home"
    assert "Observed" in row["body"]


def test_a_non_native_row_has_no_text_or_body(client: TestClient) -> None:
    rule_id, event_id = _seed()
    _add_delivery(rule_id, event_id, "telegram", status="sent")
    row = client.get("/api/alerts/deliveries").json()[0]
    assert row["text"] is None
    assert row["body"] is None


def test_a_purged_source_event_gives_a_null_text_not_a_500(client: TestClient) -> None:
    """Retention prunes place_events while the delivery row survives."""
    rule_id, _ = _seed(place_event=False)
    _add_delivery(rule_id, 999_999, "native")
    res = client.get("/api/alerts/deliveries?channel=native")
    assert res.status_code == 200
    assert res.json()[0]["text"] is None


def test_no_join_field_leaks_into_the_response(client: TestClient) -> None:
    rule_id, event_id = _seed()
    _add_delivery(rule_id, event_id, "native")
    row = client.get("/api/alerts/deliveries?channel=native").json()[0]
    assert set(row) == {
        "id",
        "rule_id",
        "rule_name",
        "channel",
        "event_kind",
        "event_id",
        "sent_at",
        "delivered_at",
        "status",
        "error",
        "text",
        "body",
    }


def test_ack_flips_a_queued_row_to_delivered(client: TestClient) -> None:
    rule_id, event_id = _seed()
    delivery_id = _add_delivery(rule_id, event_id, "native")
    assert client.post(f"/api/alerts/deliveries/{delivery_id}/ack").status_code == 204
    with session_scope() as s:
        row = s.get(AlertDelivery, delivery_id)
        assert row.status == "delivered"
        assert row.delivered_at is not None


def test_a_second_ack_is_404_not_409(client: TestClient) -> None:
    rule_id, event_id = _seed()
    delivery_id = _add_delivery(rule_id, event_id, "native")
    client.post(f"/api/alerts/deliveries/{delivery_id}/ack")
    assert client.post(f"/api/alerts/deliveries/{delivery_id}/ack").status_code == 404


def test_ack_on_a_missing_id_is_404(client: TestClient) -> None:
    assert client.post("/api/alerts/deliveries/4242/ack").status_code == 404


def test_an_acked_row_never_comes_back_through_the_cursor(client: TestClient) -> None:
    rule_id, event_id = _seed()
    delivery_id = _add_delivery(rule_id, event_id, "native")
    client.post(f"/api/alerts/deliveries/{delivery_id}/ack")
    assert client.get(f"/api/alerts/deliveries?since={delivery_id}&channel=native").json() == []


def test_both_routes_401_while_the_app_is_locked(client: TestClient) -> None:
    """Neither route joins _PUBLIC: a locked dashboard hides the queue entirely."""
    rule_id, event_id = _seed()
    delivery_id = _add_delivery(rule_id, event_id, "native")
    client.post("/api/settings/pin", json={"new_pin": "864213"})
    client.cookies.clear()
    assert client.get("/api/alerts/deliveries?channel=native").status_code == 401
    assert client.post(f"/api/alerts/deliveries/{delivery_id}/ack").status_code == 401
