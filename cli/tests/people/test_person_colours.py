"""A new person or pet gets the first palette colour nobody else uses (dashboard 1.3)."""

from __future__ import annotations

import pytest

from findplus.db.session import session_scope
from findplus.ingest import upsert_device
from findplus.labels import DEVICE_PALETTE
from findplus.people import repo
from findplus.state import track_devices


@pytest.fixture
def people_client(client):
    with session_scope() as s:
        for device_id, name in (("za", "Sam Bag"), ("zb", "Jamie Keys"), ("zc", "Rex Tag")):
            upsert_device(s, device_id, name, provider="test-fake")
        track_devices(s, ["za", "zb", "zc"])
        s.commit()
    return client


def _colour(client, name, **extra) -> str:
    resp = client.post("/api/people", json={"name": name, **extra})
    assert resp.status_code == 201, resp.text
    return resp.json()["color"]


def test_api_people_get_distinct_colours_in_palette_order(people_client):
    assert _colour(people_client, "Sam") == DEVICE_PALETTE[0]
    assert _colour(people_client, "Jamie") == DEVICE_PALETTE[1]
    assert _colour(people_client, "Rex", kind="pet") == DEVICE_PALETTE[2]


def test_explicit_colour_is_kept_and_does_not_use_up_a_palette_slot(people_client):
    assert _colour(people_client, "Sam", color="#123456") == "#123456"
    assert _colour(people_client, "Jamie") == DEVICE_PALETTE[0]


def test_deleting_a_person_frees_the_colour(people_client):
    first = people_client.post("/api/people", json={"name": "Sam"}).json()
    people_client.delete(f"/api/people/{first['id']}")
    assert _colour(people_client, "Jamie") == DEVICE_PALETTE[0]


def test_plain_sets_keep_the_green_and_do_not_use_up_a_colour(people_client):
    group = people_client.post("/api/groups", json={"name": "Kids"}).json()
    assert group["color"] == "#27ae60"
    assert _colour(people_client, "Sam") == DEVICE_PALETTE[0]


def test_group_api_person_without_colour_is_picked(people_client):
    resp = people_client.post("/api/groups", json={"name": "Sam", "kind": "person"})
    assert resp.json()["color"] == DEVICE_PALETTE[0]
    assert _colour(people_client, "Jamie") == DEVICE_PALETTE[1]


def test_existing_people_are_not_recoloured(people_client):
    sam = people_client.post("/api/people", json={"name": "Sam"}).json()
    people_client.patch(f"/api/people/{sam['id']}", json={"color": "#123456"})
    _colour(people_client, "Jamie")
    assert people_client.get(f"/api/people/{sam['id']}").json()["color"] == "#123456"


def test_colours_cycle_evenly_once_all_twelve_are_taken(session):
    for i in range(12):
        repo.create_person(session, name=f"P{i}")
    assert {p.color for p in repo.list_people(session)} == set(DEVICE_PALETTE)
    assert repo.create_person(session, name="P12").color == DEVICE_PALETTE[0]
    assert repo.create_person(session, name="P13").color == DEVICE_PALETTE[1]


def test_suggestion_accept_assigns_a_colour(people_client):
    body = {
        "accept": [{"action": "create", "name": "Sam", "members": [{"device_id": "za"}]}],
        "dismiss": [],
    }
    resp = people_client.post("/api/people/suggestions/accept", json=body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["people"][0]["color"] == DEVICE_PALETTE[0]
