"""/api/groups: CRUD, membership, presence, events, and the timeline group_id filter."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from findplus.db.session import session_scope
from findplus.ingest import ingest_observations, upsert_device
from tests.conftest import make_observation


@pytest.fixture
def client(tmp_db):
    from findplus.api import create_app

    with session_scope() as session:
        upsert_device(session, "dev1", "Tag1")
        upsert_device(session, "dev2", "Tag2")
        upsert_device(session, "dev3", "Tag3")
    return TestClient(create_app())


def _make_group_with_members(client: TestClient, member_ids: list[str]) -> int:
    group_id = client.post("/api/groups", json={"name": "Family"}).json()["id"]
    client.put(f"/api/groups/{group_id}/members", json={"member_ids": member_ids})
    return group_id


def test_post_group_creates(client: TestClient) -> None:
    res = client.post("/api/groups", json={"name": "Family"})
    assert res.status_code == 201
    body = res.json()
    assert "id" in body
    assert body["members"] == []


def test_get_groups_returns_list(client: TestClient) -> None:
    client.post("/api/groups", json={"name": "Family"})
    client.post("/api/groups", json={"name": "Work"})
    rows = client.get("/api/groups").json()
    assert len(rows) == 2


def test_put_group_updates_name(client: TestClient) -> None:
    group_id = client.post("/api/groups", json={"name": "Family"}).json()["id"]
    res = client.put(f"/api/groups/{group_id}", json={"name": "NewName"})
    assert res.status_code == 200
    assert res.json()["name"] == "NewName"


def test_delete_group_removes(client: TestClient) -> None:
    group_id = client.post("/api/groups", json={"name": "Family"}).json()["id"]
    assert client.delete(f"/api/groups/{group_id}").status_code == 204
    assert client.put(f"/api/groups/{group_id}", json={"name": "X"}).status_code == 404


def test_duplicate_name_409(client: TestClient) -> None:
    client.post("/api/groups", json={"name": "Family"})
    res = client.post("/api/groups", json={"name": "Family"})
    assert res.status_code == 409


def test_post_group_radius_out_of_range_422(client: TestClient) -> None:
    res = client.post("/api/groups", json={"name": "Family", "cluster_radius_meters": 5})
    assert res.status_code == 422


def test_post_group_stale_out_of_range_422(client: TestClient) -> None:
    res = client.post("/api/groups", json={"name": "Family", "stale_after_minutes": 1})
    assert res.status_code == 422


def test_post_group_quorum_zero_422(client: TestClient) -> None:
    res = client.post("/api/groups", json={"name": "Family", "quorum": "0"})
    assert res.status_code == 422


def test_post_group_quorum_non_numeric_422(client: TestClient) -> None:
    res = client.post("/api/groups", json={"name": "Family", "quorum": "banana"})
    assert res.status_code == 422


def test_post_group_valid_values_201(client: TestClient) -> None:
    res = client.post(
        "/api/groups",
        json={
            "name": "Family",
            "quorum": "3",
            "cluster_radius_meters": 300,
            "stale_after_minutes": 120,
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["quorum"] == "3"
    assert body["cluster_radius_meters"] == 300
    assert body["stale_after_minutes"] == 120


def test_put_group_quorum_zero_422(client: TestClient) -> None:
    group_id = client.post("/api/groups", json={"name": "Family"}).json()["id"]
    res = client.put(f"/api/groups/{group_id}", json={"quorum": "0"})
    assert res.status_code == 422


def test_put_group_radius_out_of_range_422(client: TestClient) -> None:
    group_id = client.post("/api/groups", json={"name": "Family"}).json()["id"]
    res = client.put(f"/api/groups/{group_id}", json={"cluster_radius_meters": 3000})
    assert res.status_code == 422


def test_put_members_full_replace(client: TestClient) -> None:
    group_id = _make_group_with_members(client, ["dev1", "dev2"])
    res = client.put(f"/api/groups/{group_id}/members", json={"member_ids": ["dev3"]})
    assert res.status_code == 200
    member_ids = {m["device_id"] for m in res.json()["members"]}
    assert member_ids == {"dev3"}


def test_get_presence_returns_shape(client: TestClient) -> None:
    group_id = client.post("/api/groups", json={"name": "Family"}).json()["id"]
    res = client.get(f"/api/groups/{group_id}/presence")
    assert res.status_code == 200
    body = res.json()
    for key in ("verdict", "together", "diverged", "stale", "note", "members"):
        assert key in body
    assert body["verdict"] in {"all_together", "partial", "unknown"}


def test_get_group_events_empty(client: TestClient) -> None:
    group_id = client.post("/api/groups", json={"name": "Family"}).json()["id"]
    res = client.get(f"/api/groups/events?group_id={group_id}")
    assert res.status_code == 200
    assert res.json() == []


def test_timeline_group_id_separate_tracks(client: TestClient) -> None:
    group_id = _make_group_with_members(client, ["dev1", "dev2"])
    with session_scope() as session:
        ingest_observations(
            session,
            [
                make_observation(device_id="dev1", minutes=0),
                make_observation(device_id="dev1", minutes=1),
                make_observation(device_id="dev2", minutes=0),
            ],
        )

    res = client.get(f"/api/timeline?group_id={group_id}&day=2026-09-18&timezone=UTC")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 2
    device_ids = {item["device_id"] for item in body}
    assert device_ids == {"dev1", "dev2"}


def test_timeline_group_id_invariant5_no_merge(client: TestClient) -> None:
    group_id = _make_group_with_members(client, ["dev1", "dev2"])
    with session_scope() as session:
        ingest_observations(
            session,
            [
                make_observation(device_id="dev1", minutes=0),
                make_observation(device_id="dev1", minutes=1),
                make_observation(device_id="dev2", minutes=0),
                make_observation(device_id="dev2", minutes=1),
            ],
        )

    res = client.get(f"/api/timeline?group_id={group_id}&day=2026-09-18&timezone=UTC")
    body = res.json()
    assert isinstance(body, list)
    for item in body:
        assert "device_id" in item
        other_ids = {i["device_id"] for i in body if i is not item}
        assert item["device_id"] not in other_ids


def test_timeline_group_not_found_404(client: TestClient) -> None:
    res = client.get("/api/timeline?group_id=9999&day=2026-09-18&timezone=UTC")
    assert res.status_code == 404


def test_locked(client: TestClient) -> None:
    client.post("/api/settings/pin", json={"new_pin": "8642"})
    client.cookies.clear()
    res = client.get("/api/groups")
    assert res.status_code == 401
    assert res.json()["locked"] is True


def test_group_timestamps_are_parseable(client: TestClient) -> None:
    """Every timestamp the group routes emit must round-trip through fromisoformat.

    UtcDateTime returns aware UTC, so isoformat() already carries "+00:00";
    appending a "Z" produced "...+00:00Z", which no ISO parser accepts.
    """
    from datetime import UTC, datetime

    group_id = _make_group_with_members(client, ["dev1"])
    with session_scope() as session:
        ingest_observations(
            session,
            [
                make_observation(device_id="dev1", minutes=0),
                # A fresh fix so the member is reporting, not stale, and the
                # presence route actually renders a last_observed_at.
                make_observation(device_id="dev1", observed_at=datetime.now(UTC)),
            ],
        )

    body = client.get(f"/api/groups/{group_id}/presence").json()
    stamps = [m["last_observed_at"] for m in body["members"] if m["last_observed_at"]]
    assert stamps, "expected at least one reporting member"

    points = client.get(f"/api/timeline?group_id={group_id}&day=2026-09-18&timezone=UTC").json()
    stamps += [p["observed_at"] for item in points for p in item["points"]]
    assert len(stamps) > 1

    for stamp in stamps:
        assert datetime.fromisoformat(stamp).tzinfo is not None
