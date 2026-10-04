"""`routing.endpoint` rides along in the combined GET/PATCH /api/settings body (O13)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_default_is_empty_in_the_combined_body(client: TestClient) -> None:
    assert client.get("/api/settings").json()["routing.endpoint"] == ""


def test_patch_sets_clears_and_matches_the_dedicated_route(client: TestClient) -> None:
    resp = client.patch("/api/settings", json={"routing.endpoint": "http://osrm.local:5000/"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["routing.endpoint"] == "http://osrm.local:5000"
    dedicated = client.get("/api/settings/routing.endpoint").json()
    assert dedicated == {"routing.endpoint": "http://osrm.local:5000"}
    # An unrelated PATCH leaves it alone; null clears it.
    assert client.patch("/api/settings", json={"theme": "dark"}).json()["routing.endpoint"]
    cleared = client.patch("/api/settings", json={"routing.endpoint": None})
    assert cleared.json()["routing.endpoint"] == ""


def test_a_bad_address_is_a_422_and_writes_nothing(client: TestClient) -> None:
    resp = client.patch("/api/settings", json={"routing.endpoint": "ftp://nope"})
    assert resp.status_code == 422
    assert "http" in resp.json()["detail"]
    assert client.get("/api/settings").json()["routing.endpoint"] == ""
    resp = client.patch("/api/settings", json={"routing.endpoint": 5})
    assert resp.status_code == 422
