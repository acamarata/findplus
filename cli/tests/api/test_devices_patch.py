"""PATCH /api/devices/{device_id}: labels, icons, colours and the tracked flag.

Purpose : Pin the 422 body shape api-contract.md requires (a `detail` LIST of
          `{loc, msg}` objects, not a bare string), the 404 wording, and the
          difference between clearing a label and omitting the key.
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
        upsert_device(session, "dev1", "Tag1")
    return TestClient(create_app())


def _row(client: TestClient, device_id: str = "dev1") -> dict:
    body = client.get("/api/devices").json()
    return next(d for d in body["devices"] if d["device_id"] == device_id)


def test_patch_sets_label_icon_and_color(client: TestClient) -> None:
    res = client.patch(
        "/api/devices/dev1",
        json={"label": "  Mom's keys  ", "icon": "lucide:key", "color": "#4f8cf7"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["label"] == "Mom's keys"
    assert body["icon"] == "lucide:key"
    assert body["color"] == "#4f8cf7"


def test_patch_response_matches_the_get_devices_row(client: TestClient) -> None:
    patched = client.patch("/api/devices/dev1", json={"icon": "lucide:dog"}).json()
    assert patched == _row(client)


def test_patch_unknown_device_is_404(client: TestClient) -> None:
    res = client.patch("/api/devices/unknown-id", json={"label": "x"})
    assert res.status_code == 404
    assert res.json()["detail"] == "device unknown-id not found"


@pytest.mark.parametrize(
    ("payload", "fragment"),
    [
        ({"label": "x" * 41}, "40 characters"),
        ({"icon": "bogus"}, "icon must match lucide:"),
        ({"icon": "lucide:not-real"}, "one of the available lucide icon ids"),
        ({"color": "#FFFFFF"}, "lowercase #rrggbb"),
    ],
)
def test_patch_validation_errors_use_the_pinned_detail_list(
    client: TestClient, payload: dict, fragment: str
) -> None:
    res = client.patch("/api/devices/dev1", json=payload)
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert isinstance(detail, list)
    assert fragment in detail[0]["msg"]
    assert "loc" in detail[0]


def test_empty_label_clears_a_previously_set_one(client: TestClient) -> None:
    client.patch("/api/devices/dev1", json={"label": "Mom"})
    assert _row(client)["label"] == "Mom"
    assert client.patch("/api/devices/dev1", json={"label": ""}).json()["label"] is None
    assert _row(client)["label"] is None


def test_an_omitted_label_key_leaves_the_label_alone(client: TestClient) -> None:
    client.patch("/api/devices/dev1", json={"label": "Mom"})
    client.patch("/api/devices/dev1", json={"icon": "lucide:cat"})
    row = _row(client)
    assert row["label"] == "Mom"
    assert row["icon"] == "lucide:cat"


def test_patch_toggles_tracked(client: TestClient) -> None:
    assert client.patch("/api/devices/dev1", json={"tracked": True}).json()["is_tracked"] is True
    assert _row(client)["is_tracked"] is True
    assert client.patch("/api/devices/dev1", json={"tracked": False}).json()["is_tracked"] is False
    assert _row(client)["is_tracked"] is False


def test_an_empty_body_changes_nothing(client: TestClient) -> None:
    before = _row(client)
    assert client.patch("/api/devices/dev1", json={}).json() == before


def test_a_wrong_json_type_is_422_not_500(client: TestClient) -> None:
    res = client.patch("/api/devices/dev1", json={"tracked": "not-a-bool"})
    assert res.status_code == 422
    assert isinstance(res.json()["detail"], list)


def test_a_null_icon_is_a_no_op_and_never_nulls_the_column(client: TestClient) -> None:
    """`icon`/`color` are NOT NULL: an explicit null must not reach the column."""
    client.patch("/api/devices/dev1", json={"icon": "lucide:bird", "color": "#37c67a"})
    body = client.patch("/api/devices/dev1", json={"icon": None, "color": None}).json()
    assert body["icon"] == "lucide:bird"
    assert body["color"] == "#37c67a"
