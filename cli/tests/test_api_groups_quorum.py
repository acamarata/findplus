"""A numeric quorum above the member count is a 422 on every write path (O10)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from findplus.db.models import Group
from findplus.db.session import session_scope
from findplus.ingest import upsert_device


@pytest.fixture
def client(tmp_db):
    from findplus.api import create_app

    with session_scope() as session:
        for i in range(4):
            upsert_device(session, f"d{i}", f"Tag {i}")
    return TestClient(create_app())


def _group(client: TestClient, quorum: str, members: list[str]) -> int:
    body = {"name": "G", "quorum": quorum, "member_ids": members}
    res = client.post("/api/groups", json=body)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_create_rejects_quorum_above_members(client: TestClient) -> None:
    res = client.post("/api/groups", json={"name": "G", "quorum": "3", "member_ids": ["d0", "d1"]})
    assert res.status_code == 422
    assert "quorum 3 is more than the 2 members" in res.json()["detail"]
    assert client.get("/api/groups").json() == []


def test_create_accepts_quorum_equal_to_members_and_words(client: TestClient) -> None:
    gid = _group(client, "2", ["d0", "d1"])
    client.delete(f"/api/groups/{gid}")
    assert client.post("/api/groups", json={"name": "A", "quorum": "all"}).status_code == 201


def test_create_with_no_members_yet_is_allowed(client: TestClient) -> None:
    res = client.post("/api/groups", json={"name": "Later", "quorum": "3"})
    assert res.status_code == 201


def test_update_quorum_above_current_members_is_422(client: TestClient) -> None:
    gid = _group(client, "any", ["d0", "d1"])
    res = client.put(f"/api/groups/{gid}", json={"quorum": "5"})
    assert res.status_code == 422
    assert client.get("/api/groups").json()[0]["quorum"] == "any"


def test_update_quorum_and_members_together_are_checked_together(client: TestClient) -> None:
    gid = _group(client, "any", ["d0"])
    res = client.put(f"/api/groups/{gid}", json={"quorum": "3", "member_ids": ["d0", "d1", "d2"]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["quorum"] == "3"
    assert len(body["members"]) == 3
    bad = client.put(f"/api/groups/{gid}", json={"quorum": "4", "member_ids": ["d0", "d1", "d2"]})
    assert bad.status_code == 422


def test_removing_members_below_the_quorum_is_422_and_changes_nothing(client: TestClient) -> None:
    gid = _group(client, "3", ["d0", "d1", "d2"])
    res = client.put(f"/api/groups/{gid}/members", json={"member_ids": ["d0"]})
    assert res.status_code == 422
    assert "lower the quorum" in res.json()["detail"]
    assert len(client.get("/api/groups").json()[0]["members"]) == 3
    # Lowering the quorum and the members in one PUT works.
    ok = client.put(f"/api/groups/{gid}", json={"quorum": "1", "member_ids": ["d0"]})
    assert ok.status_code == 200, ok.text


def test_an_old_group_over_its_members_stays_editable(client: TestClient) -> None:
    gid = _group(client, "any", ["d0"])
    with session_scope() as session:
        session.get(Group, gid).quorum = "5"
    res = client.put(f"/api/groups/{gid}", json={"color": "#112233"})
    assert res.status_code == 200, res.text
