"""/api/people: CRUD, suggestions, tracker roles, left-behind, settings, the lock."""

from __future__ import annotations

import pytest

from findplus.db.session import session_scope
from findplus.ingest import upsert_device
from findplus.state import track_devices


@pytest.fixture
def people_client(client):
    with session_scope() as s:
        for device_id, name in (("zb", "Sam Bag"), ("zr", "Sam Shoes Red"), ("am", "Jamie")):
            upsert_device(s, device_id, name, provider="test-fake")
        track_devices(s, ["zb", "zr", "am"])
        s.commit()
    return client


def _sam(client) -> int:
    return client.post("/api/people", json={"name": "Sam", "member_ids": ["zb"]}).json()["id"]


def test_suggestions_then_accept_creates_the_person(people_client):
    preview = people_client.get("/api/people/suggestions").json()
    sam = next(s for s in preview["suggestions"] if s["name"] == "Sam")
    body = {
        "accept": [
            {"action": "create", "name": "Sam", "kind": "person",
             "members": [{"device_id": "zb", "role": "bag"}, {"device_id": "zr"}]}
        ],
        "dismiss": [],
    }  # fmt: skip
    assert sam["action"] == "create"
    resp = people_client.post("/api/people/suggestions/accept", json=body)
    assert resp.status_code == 200, resp.text
    person = resp.json()["people"][0]
    roles = {t["device_id"]: (t["role"], t["role_source"]) for t in person["trackers"]}
    assert roles == {"zb": ("bag", "set"), "zr": ("shoes", "name")}
    listed = people_client.get("/api/people").json()
    assert [p["name"] for p in listed] == ["Sam"]


def test_crud_and_one_person_per_tracker_is_409(people_client):
    created = people_client.post("/api/people", json={"name": "Sam", "member_ids": ["zb", "zr"]})
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    clash = people_client.post("/api/people", json={"name": "Brother", "member_ids": ["zb"]})
    assert clash.status_code == 409 and "already belongs to Sam" in clash.json()["detail"]
    group = people_client.post("/api/groups", json={"name": "Kids", "member_ids": ["zb"]})
    assert group.status_code == 201  # a set may share trackers with a person
    to_person = people_client.put(f"/api/groups/{group.json()['id']}", json={"kind": "person"})
    assert to_person.status_code == 409
    renamed = people_client.patch(f"/api/people/{pid}", json={"name": "Sam A"})
    assert renamed.json()["name"] == "Sam A"
    assert people_client.get(f"/api/people/{pid}").json()["kind"] == "person"
    assert (
        people_client.put(f"/api/people/{pid}/members", json={"member_ids": ["zr"]}).status_code
        == 200
    )
    assert people_client.delete(f"/api/people/{pid}").status_code == 204
    assert people_client.get(f"/api/people/{pid}").status_code == 404


def test_a_set_is_not_a_person(people_client):
    gid = people_client.post("/api/groups", json={"name": "Kids", "member_ids": []}).json()["id"]
    assert people_client.get(f"/api/people/{gid}").status_code == 404
    bad = people_client.post("/api/groups", json={"name": "X", "kind": "robot"})
    assert bad.status_code == 422


def test_tracker_role_and_weight(people_client):
    resp = people_client.put(
        "/api/people/trackers/zb", json={"role": "jacket", "carry_weight": 0.3}
    )
    assert resp.json() == {"device_id": "zb", "role": "jacket", "carry_weight": 0.3}
    cleared = people_client.put("/api/people/trackers/zb", json={"carry_weight": None})
    assert cleared.json()["role"] == "jacket" and cleared.json()["carry_weight"] is None
    assert people_client.put("/api/people/trackers/zb", json={"role": "rocket"}).status_code == 422
    over = people_client.put("/api/people/trackers/zb", json={"carry_weight": 2})
    assert over.status_code == 422
    assert people_client.put("/api/people/trackers/nope", json={"role": "bag"}).status_code == 404


def test_now_and_left_behind_and_settings(people_client):
    pid = people_client.post("/api/people", json={"name": "Sam", "member_ids": ["zb"]}).json()["id"]
    now = people_client.get(f"/api/people/{pid}/now").json()
    assert now["person"]["name"] == "Sam" and now["confidence"] == "unknown"
    assert now["text"] == "No recent sightings."
    assert people_client.get(f"/api/people/{pid}/left-behind").json() == []
    missing = people_client.post(f"/api/people/{pid}/left-behind/99/dismiss")
    assert missing.status_code == 404
    assert people_client.get("/api/people/settings").json() == {"left_behind_alerts": True}
    off = people_client.put("/api/people/settings", json={"left_behind_alerts": False})
    assert off.json() == {"left_behind_alerts": False}


def test_every_people_route_401s_while_locked(people_client):
    pid = people_client.post("/api/people", json={"name": "Sam", "member_ids": ["zb"]}).json()["id"]
    pin = "000000"
    assert people_client.post("/api/settings/pin", json={"new_pin": pin}).status_code == 200
    people_client.cookies.clear()
    for method, path in (
        ("get", "/api/people"),
        ("get", "/api/people/suggestions"),
        ("post", "/api/people/suggestions/accept"),
        ("get", f"/api/people/{pid}"),
        ("get", f"/api/people/{pid}/now"),
        ("get", f"/api/people/{pid}/left-behind"),
        ("put", "/api/people/trackers/zb"),
        ("get", "/api/people/settings"),
        ("post", "/api/places/notify-defaults"),
    ):
        resp = getattr(people_client, method)(path)
        assert resp.status_code == 401, (path, resp.status_code)
        assert "Sam" not in resp.text
    people_client.post("/api/lock/unlock", json={"pin": pin})
