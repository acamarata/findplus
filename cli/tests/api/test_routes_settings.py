"""/api/settings/widget.show_map: the per-key GET/PUT/POST round-trip.

Purpose    : Cover the P1-E10-S2 fix-loop route (build-notes.md defect #36) —
             the dashboard's widget-map checkbox 404'd until this route
             landed alongside the existing app.start_at_login pair.
Inputs     : TestClient against a freshly created app (fixtures reused from
             tests.test_api so 401-while-locked matches every other route).
Outputs    : Assertions on response shape and the underlying settings-table
             row (`get_setting(session, "widget.show_map")`).
Constraints: Never touches the real ~/.findplus or the network.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from findplus.db.session import session_scope
from findplus.state import get_setting
from tests.test_api import client, locked_client  # noqa: F401


def test_widget_show_map_defaults_false(client: TestClient) -> None:  # noqa: F811
    body = client.get("/api/settings/widget.show_map").json()
    assert body == {"widget.show_map": False}


def test_widget_show_map_put_and_post_roundtrip(client: TestClient) -> None:  # noqa: F811
    put_body = client.put("/api/settings/widget.show_map", json={"value": True}).json()
    assert put_body == {"widget.show_map": True}
    assert client.get("/api/settings/widget.show_map").json() == {"widget.show_map": True}

    post_body = client.post("/api/settings/widget.show_map", json={"value": False}).json()
    assert post_body == {"widget.show_map": False}
    assert client.get("/api/settings/widget.show_map").json() == {"widget.show_map": False}


def test_widget_show_map_writes_the_settings_table_row(client: TestClient) -> None:  # noqa: F811
    resp = client.post("/api/settings/widget.show_map", json={"value": True})
    assert resp.status_code == 200, resp.text
    with session_scope() as session:
        assert get_setting(session, "widget.show_map") == "1"


def test_widget_show_map_locked(locked_client: TestClient) -> None:  # noqa: F811
    path = "/api/settings/widget.show_map"
    assert locked_client.get(path).status_code == 401
    assert locked_client.put(path, json={"value": True}).status_code == 401
    assert locked_client.post(path, json={"value": True}).status_code == 401


def test_widget_show_map_rejects_non_bool(client: TestClient) -> None:  # noqa: F811
    resp = client.post("/api/settings/widget.show_map", json={"value": "not-a-bool"})
    assert resp.status_code == 422
    resp = client.put("/api/settings/widget.show_map", json={"value": "not-a-bool"})
    assert resp.status_code == 422
