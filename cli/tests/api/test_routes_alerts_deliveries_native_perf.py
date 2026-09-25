"""CF-P2-16: batched rendering of /api/alerts/deliveries must reproduce the
old per-row output byte for byte, and its statement count must not grow
with row count. Split from test_routes_alerts_deliveries_native.py (E13
stage 2, size cap).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event as sa_event

from findplus.db.session import get_engine

from ._native_delivery_helpers import _add_delivery, _seed, _seed_group


@pytest.fixture
def client(tmp_db):
    from findplus.api import create_app

    return TestClient(create_app())


@pytest.fixture(autouse=True)
def _pin_render_tz(pinned_tz):
    """The rendered body is in the machine's local zone (render_message()),
    while the seeded event time below is a fixed UTC instant -- pin the
    process to UTC so the snapshot text below is the same on any host. This
    is a render-timezone choice, not an API-timestamp one: `sent_at` etc. in
    `_BASE_ROW` stay UTC ISO-8601 either way.
    """
    pinned_tz("UTC")


_DEVICE_BODY = (
    "Observed 2026-09-20 12:00 UTC · reported 12:00 UTC · 0 min late\n"
    "Confidence: high.\n"
    "Alerts inherit the network's delay. An arrival or departure may be "
    "reported minutes to hours late."
)
_GROUP_BODY = (
    "Observed 2026-09-20 12:00 UTC · reported unknown · lag unknown\n"
    "Confidence: medium. 2 of 3 tags entered Home; 1 tag has no recent fix.\n"
    "Alerts inherit the network's delay. An arrival or departure may be "
    "reported minutes to hours late."
)
_BASE_ROW = {
    "rule_name": "native rule",
    "channel": "native",
    "target": "",
    "sent_at": "2026-09-20T12:00:00+00:00",
    "delivered_at": None,
    "status": "queued",
    "error": None,
    "attempts": 1,
    "next_attempt_at": None,
}


def _expected_row(id_: int, rule_id: int, event_kind: str, event_id: int, text, body):
    return {
        **_BASE_ROW,
        "id": id_,
        "rule_id": rule_id,
        "event_kind": event_kind,
        "event_id": event_id,
        "text": text,
        "body": body,
    }


def test_batched_rendering_is_byte_identical_to_the_old_per_row_output(
    client: TestClient,
) -> None:
    """Snapshot captured from the pre-batching code (one query per row) with a
    device row, a purged device row, and a group row. The batched rewrite
    must reproduce this exact JSON, field for field.
    """
    rule_id, device_event_id = _seed()
    group_event_id = _seed_group()
    _add_delivery(rule_id, device_event_id, "native")
    _add_delivery(rule_id, 999_999, "native")
    _add_delivery(rule_id, group_event_id, "native", event_kind="group")

    rows = client.get("/api/alerts/deliveries?channel=native").json()
    expected = [
        _expected_row(1, rule_id, "device", device_event_id, "Tag arrived at Home", _DEVICE_BODY),
        _expected_row(2, rule_id, "device", 999_999, None, None),
        _expected_row(3, rule_id, "group", group_event_id, "Family arrived at Home", _GROUP_BODY),
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
