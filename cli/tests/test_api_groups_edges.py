"""/api/groups with the inputs a real 17-tracker account produces.

Duplicate member ids, an id that is not a device, names that differ only by
case or trailing space, and every member without a fix.
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
        for i in range(17):
            upsert_device(session, f"D{i:02d}", "Ali Pixel 8a" if i < 2 else f"Tag {i}")
    return TestClient(create_app(), raise_server_exceptions=False)


def test_duplicate_member_ids_are_collapsed(client: TestClient) -> None:
    res = client.post("/api/groups", json={"name": "Dup", "member_ids": ["D00", "D00", "D01"]})
    assert res.status_code == 201, res.text
    assert [m["device_id"] for m in res.json()["members"]] == ["D00", "D01"]


def test_duplicate_member_ids_in_set_members(client: TestClient) -> None:
    gid = client.post("/api/groups", json={"name": "G"}).json()["id"]
    res = client.put(f"/api/groups/{gid}/members", json={"member_ids": ["D00", "D00"]})
    assert res.status_code == 200, res.text
    assert len(res.json()["members"]) == 1


def test_unknown_member_on_create_is_a_clear_error(client: TestClient) -> None:
    res = client.post("/api/groups", json={"name": "Ghost", "member_ids": ["NOPE"]})
    assert res.status_code == 404, res.text
    assert "NOPE" in res.json()["detail"]
    # Nothing half-created: the same name can be tried again.
    assert client.get("/api/groups").json() == []


def test_name_differing_only_by_case_or_space_is_a_duplicate(client: TestClient) -> None:
    assert client.post("/api/groups", json={"name": "Kids"}).status_code == 201
    assert client.post("/api/groups", json={"name": "kids"}).status_code == 409
    assert client.post("/api/groups", json={"name": " Kids "}).status_code == 409


def test_blank_name_is_rejected(client: TestClient) -> None:
    assert client.post("/api/groups", json={"name": "   "}).status_code == 422


def test_rename_conflict_message_names_the_group(client: TestClient) -> None:
    client.post("/api/groups", json={"name": "A"})
    gid = client.post("/api/groups", json={"name": "B"}).json()["id"]
    res = client.put(f"/api/groups/{gid}", json={"name": "A"})
    assert res.status_code == 409
    assert "already exists" in res.json()["detail"]


def test_group_of_members_without_fixes_explains_itself(client: TestClient) -> None:
    gid = client.post(
        "/api/groups", json={"name": "Silent", "member_ids": [f"D{i:02d}" for i in range(17)]}
    ).json()["id"]
    body = client.get(f"/api/groups/{gid}/presence").json()
    assert body["verdict"] == "unknown"
    assert body["reporting_count"] == 0
    assert body["considered_count"] == 17
    assert len(body["members"]) == 17
    assert "not reported" in body["note"]
