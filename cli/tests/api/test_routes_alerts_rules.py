"""/api/alerts/rules CRUD and /api/alerts/deliveries. Split from
test_routes_alerts.py (E13 stage 2, size cap).
"""

from __future__ import annotations

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


def test_rules_crud(client: TestClient) -> None:
    # "native" needs no configured credentials (UAT2 U11's server-side
    # check requires at least one connected channel); this test does not
    # care which channel, only that CRUD works.
    create = client.post(
        "/api/alerts/rules",
        json={"name": "r1", "device_id": "dev1", "channels": ["native"]},
    )
    assert create.status_code == 201
    body = create.json()
    assert body["device_id"] == "dev1"
    rule_id = body["id"]

    listed = client.get("/api/alerts/rules").json()
    assert any(r["id"] == rule_id for r in listed)

    updated = client.put(f"/api/alerts/rules/{rule_id}", json={"enabled": False})
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False

    deleted = client.delete(f"/api/alerts/rules/{rule_id}")
    assert deleted.status_code == 204

    assert client.get("/api/alerts/rules").json() == []


def test_rules_create_requires_exactly_one_target(client: TestClient) -> None:
    res = client.post("/api/alerts/rules", json={"name": "bad", "channels": ["telegram"]})
    assert res.status_code == 422


def test_rules_list_shows_the_device_label_not_the_provider_name(client: TestClient) -> None:
    """UAT U6: the rules table and the rule form's own Device select both
    read this same field, so it must be the label the user gave the tracker."""
    with session_scope() as session:
        from findplus.db.models import Device

        session.get(Device, "dev1").label = "Sara's backpack"
        session.commit()
    create = client.post(
        "/api/alerts/rules",
        json={"name": "r1", "device_id": "dev1", "channels": ["native"]},
    )
    assert create.json()["device_name"] == "Sara's backpack"
    assert client.get("/api/alerts/rules").json()[0]["device_name"] == "Sara's backpack"


def test_deliveries_empty(client: TestClient) -> None:
    assert client.get("/api/alerts/deliveries").json() == []


def test_deliveries_limit_is_bounded(client: TestClient) -> None:
    """CR-C closeout m7: unbounded `limit` could grow `rows` (and the
    native-channel IN-list batch_delivery_text_bodies builds from it) past
    SQLite's variable cap and 500. 500 itself is accepted; above it is a
    plain validation 422, not a query that gets to run at all.
    """
    assert client.get("/api/alerts/deliveries", params={"limit": 500}).status_code == 200
    assert client.get("/api/alerts/deliveries", params={"limit": 501}).status_code == 422


def test_deliveries_include_channel(client: TestClient) -> None:
    """The delivery log names the channel (CF-14).

    It was a join onto the rule until migration 0008 gave alert_deliveries its own
    channel column; one event under a multi-channel rule now produces one row per
    channel, so the row has to carry it or the UI cannot show which way each went.
    """
    import datetime

    from findplus.db.models_alerts import AlertDelivery, AlertRule

    # UAT2 U11: the server now requires at least one connected channel, and
    # this test asserts the delivery row's channel is specifically
    # "webhook", so a real (if fake) credential goes in first.
    assert (
        client.put(
            "/api/alerts/channels/webhook", json={"url": "https://example.com/hook"}
        ).status_code
        == 200
    )
    rule_id = client.post(
        "/api/alerts/rules",
        json={"name": "webhook rule", "device_id": "dev1", "channels": ["webhook"]},
    ).json()["id"]

    with session_scope() as session:
        rule = session.get(AlertRule, rule_id)
        assert rule.channels == "webhook"
        session.add(
            AlertDelivery(
                rule_id=rule_id,
                event_kind="device",
                event_id=1,
                channel="webhook",
                sent_at=datetime.datetime.now(datetime.UTC),
                status="sent",
                error=None,
            )
        )

    row = client.get("/api/alerts/deliveries").json()[0]

    assert row["channel"] == "webhook"
    assert row["rule_name"] == "webhook rule"
    assert row["status"] == "sent"


def test_deliveries_include_retry_fields(client: TestClient) -> None:
    """attempts/next_attempt_at (2026-09-22 retry feature) round-trip through the API."""
    import datetime

    from findplus.db.models_alerts import AlertDelivery

    rule_id = client.post(
        "/api/alerts/rules",
        json={"name": "retry rule", "device_id": "dev1", "channels": ["native"]},
    ).json()["id"]
    now = datetime.datetime.now(datetime.UTC)
    next_attempt = now + datetime.timedelta(minutes=1)

    with session_scope() as session:
        session.add(
            AlertDelivery(
                rule_id=rule_id,
                event_kind="device",
                event_id=1,
                channel="telegram",
                sent_at=now,
                status="retrying",
                error="timeout",
                attempts=1,
                next_attempt_at=next_attempt,
            )
        )

    row = client.get("/api/alerts/deliveries").json()[0]
    assert row["status"] == "retrying"
    assert row["attempts"] == 1
    assert row["next_attempt_at"] is not None


def test_deliveries_next_attempt_at_is_null_when_not_retrying(client: TestClient) -> None:
    import datetime

    from findplus.db.models_alerts import AlertDelivery

    rule_id = client.post(
        "/api/alerts/rules",
        json={"name": "sent rule", "device_id": "dev1", "channels": ["native"]},
    ).json()["id"]

    with session_scope() as session:
        session.add(
            AlertDelivery(
                rule_id=rule_id,
                event_kind="device",
                event_id=1,
                channel="telegram",
                sent_at=datetime.datetime.now(datetime.UTC),
                status="sent",
                error=None,
            )
        )

    row = client.get("/api/alerts/deliveries").json()[0]
    assert row["attempts"] == 1
    assert row["next_attempt_at"] is None


def test_rules_create_rejects_unknown_channel(client: TestClient) -> None:
    res = client.post(
        "/api/alerts/rules", json={"name": "bad", "device_id": "dev1", "channels": ["email"]}
    )
    assert res.status_code == 422


def test_rules_create_rejects_out_of_range_cooldown(client: TestClient) -> None:
    res = client.post(
        "/api/alerts/rules",
        json={
            "name": "bad",
            "device_id": "dev1",
            "channels": ["telegram"],
            "cooldown_minutes": 5000,
        },
    )
    assert res.status_code == 422


def test_rules_accept_several_channels_and_echo_them_sorted(client: TestClient) -> None:
    res = client.post(
        "/api/alerts/rules",
        json={"name": "multi", "device_id": "dev1", "channels": ["telegram", "native"]},
    )
    assert res.status_code == 201
    assert res.json()["channels"] == ["native", "telegram"]


def test_rules_create_rejects_an_empty_channel_list(client: TestClient) -> None:
    res = client.post(
        "/api/alerts/rules", json={"name": "bad", "device_id": "dev1", "channels": []}
    )
    assert res.status_code == 422


def test_rules_create_rejects_an_unknown_channel_in_a_list(client: TestClient) -> None:
    res = client.post(
        "/api/alerts/rules",
        json={"name": "bad", "device_id": "dev1", "channels": ["telegram", "sms"]},
    )
    assert res.status_code == 422


def test_put_channels_leaves_every_other_field_alone(client: TestClient) -> None:
    rule_id = client.post(
        "/api/alerts/rules",
        json={
            "name": "keepme",
            "device_id": "dev1",
            "channels": ["native"],
            "cooldown_minutes": 7,
            "on_exit": False,
        },
    ).json()["id"]
    res = client.put(f"/api/alerts/rules/{rule_id}", json={"channels": ["whatsapp", "native"]})
    assert res.status_code == 200
    body = res.json()
    assert body["channels"] == ["native", "whatsapp"]
    assert body["name"] == "keepme"
    assert body["cooldown_minutes"] == 7
    assert body["on_exit"] is False


def test_put_rejects_an_unknown_channel_without_touching_the_rule(client: TestClient) -> None:
    rule_id = client.post(
        "/api/alerts/rules",
        json={"name": "keepme", "device_id": "dev1", "channels": ["native"]},
    ).json()["id"]
    assert (
        client.put(f"/api/alerts/rules/{rule_id}", json={"channels": ["bogus"]}).status_code == 422
    )
    assert client.get("/api/alerts/rules").json()[0]["channels"] == ["native"]
