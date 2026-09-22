"""GET /api/alerts/deliveries (since/channel/text/body) and POST .../{id}/ack.

Purpose : Pin the queue contract the desktop native poller drains -- the cursor,
          the channel filter, the rendered text, the ack's 204-then-404, and the
          401 a locked session gets from both routes.
"""

from __future__ import annotations

import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event as sa_event

from findplus.db.models import (
    Device,
    Group,
    GroupPlaceEvent,
    LocationObservation,
    Place,
    PlaceEvent,
)
from findplus.db.models_alerts import AlertDelivery, AlertRule
from findplus.db.session import get_engine, session_scope

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


def _add_delivery(
    rule_id: int, event_id: int, channel: str, status: str = "queued", event_kind: str = "device"
) -> int:
    with session_scope() as s:
        row = AlertDelivery(
            rule_id=rule_id,
            event_kind=event_kind,
            event_id=event_id,
            channel=channel,
            sent_at=NOW,
            status=status,
        )
        s.add(row)
        s.commit()
        return row.id


def _seed_group() -> int:
    """A group + one group_place_event at place_id=1 (from `_seed()`); returns its id."""
    with session_scope() as s:
        s.add(
            Group(
                id=1,
                name="Family",
                color="#27ae60",
                icon="lucide:users",
                quorum="majority",
                cluster_radius_meters=150,
                stale_after_minutes=90,
                created_at=NOW,
            )
        )
        s.flush()
        row = GroupPlaceEvent(
            group_id=1,
            place_id=1,
            event_type="ENTER",
            observed_at=NOW,
            member_event_ids="[]",
            members_crossed=2,
            members_considered=3,
            members_stale=1,
            confidence="medium",
            notified_at=None,
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


def test_batched_rendering_is_byte_identical_to_the_old_per_row_output(
    client: TestClient,
) -> None:
    """CF-P2-16 snapshot: captured from the pre-batching code (one query per row)
    with a device row, a purged device row, and a group row. The batched
    rewrite must reproduce this exact JSON, field for field.
    """
    rule_id, device_event_id = _seed()
    group_event_id = _seed_group()
    _add_delivery(rule_id, device_event_id, "native")
    _add_delivery(rule_id, 999_999, "native")
    _add_delivery(rule_id, group_event_id, "native", event_kind="group")

    rows = client.get("/api/alerts/deliveries?channel=native").json()

    expected = [
        {
            "id": 1,
            "rule_id": rule_id,
            "rule_name": "native rule",
            "channel": "native",
            "event_kind": "device",
            "event_id": device_event_id,
            "sent_at": "2026-09-20T12:00:00+00:00",
            "delivered_at": None,
            "status": "queued",
            "error": None,
            "text": "Tag arrived at Home",
            "body": (
                "Observed 2026-09-20 08:00 EDT · reported 08:00 · 0 min late\n"
                "Confidence: high.\n"
                "Alerts inherit the network's delay. An arrival or departure may be "
                "reported minutes to hours late."
            ),
        },
        {
            "id": 2,
            "rule_id": rule_id,
            "rule_name": "native rule",
            "channel": "native",
            "event_kind": "device",
            "event_id": 999_999,
            "sent_at": "2026-09-20T12:00:00+00:00",
            "delivered_at": None,
            "status": "queued",
            "error": None,
            "text": None,
            "body": None,
        },
        {
            "id": 3,
            "rule_id": rule_id,
            "rule_name": "native rule",
            "channel": "native",
            "event_kind": "group",
            "event_id": group_event_id,
            "sent_at": "2026-09-20T12:00:00+00:00",
            "delivered_at": None,
            "status": "queued",
            "error": None,
            "text": "Family arrived at Home",
            "body": (
                "Observed 2026-09-20 08:00 EDT · reported unknown · lag unknown\n"
                "Confidence: medium. 2 of 3 tags entered Home; 1 tag has no recent fix.\n"
                "Alerts inherit the network's delay. An arrival or departure may be "
                "reported minutes to hours late."
            ),
        },
    ]
    assert sorted(rows, key=lambda r: r["id"]) == sorted(expected, key=lambda r: r["id"])


def test_deliveries_statement_count_does_not_grow_with_row_count(client: TestClient) -> None:
    """CF-P2-16: rendering N native rows must run a constant number of
    statements, not one lookup query per row.
    """
    rule_id, event_id = _seed()

    def _statement_count() -> int:
        # `session_scope()` calls `get_engine(database_url)` with an explicit
        # None default, a different lru_cache key from a bare `get_engine()`
        # call -- pass None explicitly to get the same cached engine instance.
        engine = get_engine(None)
        count = 0

        def _tick(*_args: object, **_kwargs: object) -> None:
            nonlocal count
            count += 1

        sa_event.listen(engine, "before_cursor_execute", _tick)
        try:
            res = client.get("/api/alerts/deliveries?channel=native")
            assert res.status_code == 200
        finally:
            sa_event.remove(engine, "before_cursor_execute", _tick)
        return count

    # Distinct event_ids: (rule_id, event_kind, event_id, channel) is unique.
    for i in range(3):
        _add_delivery(rule_id, event_id + i, "native")
    small = _statement_count()

    for i in range(3, 30):
        _add_delivery(rule_id, event_id + i, "native")
    big = _statement_count()

    assert big == small, f"statement count grew with row count: {small} -> {big}"
    assert big <= 10, f"expected O(1) statements for a native page, got {big}"


def test_both_routes_401_while_the_app_is_locked(client: TestClient) -> None:
    """Neither route joins _PUBLIC: a locked dashboard hides the queue entirely."""
    rule_id, event_id = _seed()
    delivery_id = _add_delivery(rule_id, event_id, "native")
    client.post("/api/settings/pin", json={"new_pin": "864213"})
    client.cookies.clear()
    assert client.get("/api/alerts/deliveries?channel=native").status_code == 401
    assert client.post(f"/api/alerts/deliveries/{delivery_id}/ack").status_code == 401
