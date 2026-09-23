"""GET /api/alerts/deliveries (since/channel/text/body) and POST .../{id}/ack.

Purpose : Pin the queue contract the desktop native poller drains -- the cursor,
          the channel filter, the rendered text, the ack's 204-then-404, and the
          401 a locked session gets from both routes.

The CF-P2-16 batched-rendering snapshot and statement-count tests moved to
test_routes_alerts_deliveries_native_perf.py (E13 stage 2, size cap); the
shared seed helpers moved to _native_delivery_helpers.py.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from findplus.db.models_alerts import AlertDelivery
from findplus.db.session import session_scope

from ._native_delivery_helpers import _add_delivery, _seed


@pytest.fixture
def client(tmp_db):
    from findplus.api import create_app

    return TestClient(create_app())


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


def test_a_native_row_uses_the_device_label_when_set(client: TestClient) -> None:
    """UAT U7: the queued notification's own text is rendered on read, so it
    must resolve the tracker's label the same way the other channels do."""
    rule_id, event_id = _seed(label="Biscuit (dog)")
    _add_delivery(rule_id, event_id, "native")
    row = client.get("/api/alerts/deliveries?channel=native").json()[0]
    assert row["text"] == "Biscuit (dog) arrived at Home"


def test_a_native_row_renders_even_when_the_request_is_unfiltered(client: TestClient) -> None:
    """UAT3 N18: the dashboard's delivery log calls GET /api/alerts/deliveries
    with no `channel` filter at all -- rendering used to be gated on the
    REQUEST'S filter equalling "native", not on the row's own channel, so
    every row (including native ones) came back text:null unless the caller
    filtered to exactly `?channel=native`."""
    rule_id, event_id = _seed()
    _add_delivery(rule_id, event_id, "native")
    row = client.get("/api/alerts/deliveries").json()[0]
    assert row["text"] == "Tag arrived at Home"
    assert "Observed" in row["body"]


def test_a_non_native_row_renders_text_and_body_too(client: TestClient) -> None:
    """UAT4 N32: a telegram/whatsapp/webhook row's (event_kind, event_id) is
    exactly as renderable as a native row's -- gating on `channel == "native"`
    only hid text the server could already produce."""
    rule_id, event_id = _seed()
    _add_delivery(rule_id, event_id, "telegram", status="sent")
    row = client.get("/api/alerts/deliveries").json()[0]
    assert row["text"] == "Tag arrived at Home"
    assert "Observed" in row["body"]


def test_a_non_native_purged_source_event_gives_a_null_text_too(client: TestClient) -> None:
    """The one real gap left after N32: a purged source event still renders
    (None, None) for any channel, not just native."""
    rule_id, _ = _seed(place_event=False)
    _add_delivery(rule_id, 999_999, "telegram", status="sent")
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
        "attempts",
        "next_attempt_at",
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
