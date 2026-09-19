"""GET /api/export?group_id=... — one track per group member, never merged."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from findplus.db.session import session_scope
from findplus.groups.repo import create_group
from findplus.ingest import ingest_observations, upsert_device
from tests.conftest import make_observation


@pytest.fixture
def group_client(tmp_db):
    from findplus.api import create_app

    with session_scope() as session:
        upsert_device(session, "TAG-A", "Tag A")
        upsert_device(session, "TAG-B", "Tag B")
        ingest_observations(
            session,
            [
                make_observation(device_id="TAG-A", device_name="Tag A", minutes=0, lat=41.10),
                make_observation(device_id="TAG-A", device_name="Tag A", minutes=10, lat=41.11),
                make_observation(device_id="TAG-A", device_name="Tag A", minutes=20, lat=41.12),
                make_observation(device_id="TAG-B", device_name="Tag B", minutes=5, lat=42.10),
                make_observation(device_id="TAG-B", device_name="Tag B", minutes=15, lat=42.11),
                make_observation(device_id="TAG-B", device_name="Tag B", minutes=25, lat=42.12),
            ],
            fetched_at=datetime(2026, 9, 18, 13, 0, tzinfo=UTC),
        )
        group = create_group(session, name="Family", member_ids=["TAG-A", "TAG-B"])
        group_id = group.id

    client = TestClient(create_app())
    return client, group_id


def test_export_group_csv_has_device_id_first(group_client) -> None:
    client, group_id = group_client
    resp = client.get(f"/api/export?group_id={group_id}&fmt=csv")
    assert resp.status_code == 200
    lines = resp.text.strip().splitlines()
    header = lines[0].split(",")
    assert header[0] == "device_id"
    device_ids = {line.split(",")[0] for line in lines[1:]}
    assert device_ids == {"TAG-A", "TAG-B"}


def test_export_group_json_has_device_id_per_row(group_client) -> None:
    client, group_id = group_client
    resp = client.get(f"/api/export?group_id={group_id}&fmt=json")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 6
    assert all("device_id" in row for row in rows)
    assert {row["device_id"] for row in rows} == {"TAG-A", "TAG-B"}


def test_export_group_not_found(group_client) -> None:
    client, _group_id = group_client
    resp = client.get("/api/export?group_id=nonexistent-id&fmt=csv")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "group not found"}


def test_export_without_group_id_still_works(group_client) -> None:
    client, _group_id = group_client
    resp = client.get("/api/export?fmt=csv")
    assert resp.status_code == 200
