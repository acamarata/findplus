"""The two onboarding.* settings keys, per-key and on the collection route.

Purpose    : Pin specs/onboarding.md § 1/§ 2 — two settings-table keys reachable
             as `GET/POST /api/settings/onboarding.<key>`, merged into
             `GET /api/settings` under their DOTTED wire names, and writable on
             the PATCH collection route under the same dotted aliases (ruling F6).
Inputs     : TestClient fixtures from cli/tests/conftest.py (`client`,
             `locked_client`), same ones test_routes_settings.py uses.
Outputs    : Assertions on response bodies and the settings-table rows behind them.
Constraints: Never touches the real ~/.findplus or the network. An unknown step
             id is a 422, never a 400, so a stale client cannot wedge a future
             session on a step that does not exist.
Ticket     : P2-E11-W4-S1-T1.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from findplus.db.session import session_scope
from findplus.state import get_setting

_COMPLETED = "/api/settings/onboarding.completed_at"
_LAST_STEP = "/api/settings/onboarding.last_step"
_STAMP = "2026-09-20T12:00:00Z"


def test_completed_at_defaults_to_null(client: TestClient) -> None:
    assert client.get(_COMPLETED).json() == {"onboarding.completed_at": None}


def test_last_step_defaults_to_null(client: TestClient) -> None:
    assert client.get(_LAST_STEP).json() == {"onboarding.last_step": None}


def test_completed_at_roundtrips_an_iso_string(client: TestClient) -> None:
    posted = client.post(_COMPLETED, json={"value": _STAMP})
    assert posted.status_code == 200, posted.text
    assert posted.json() == {"onboarding.completed_at": _STAMP}
    assert client.get(_COMPLETED).json() == {"onboarding.completed_at": _STAMP}
    with session_scope() as session:
        assert get_setting(session, "onboarding.completed_at") == _STAMP


def test_completed_at_null_uncompletes_onboarding(client: TestClient) -> None:
    client.post(_COMPLETED, json={"value": _STAMP})
    cleared = client.post(_COMPLETED, json={"value": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json() == {"onboarding.completed_at": None}
    assert client.get(_COMPLETED).json() == {"onboarding.completed_at": None}


def test_last_step_roundtrips_a_known_step(client: TestClient) -> None:
    posted = client.post(_LAST_STEP, json={"value": "devices"})
    assert posted.status_code == 200, posted.text
    assert posted.json() == {"onboarding.last_step": "devices"}
    assert client.get(_LAST_STEP).json() == {"onboarding.last_step": "devices"}


def test_last_step_rejects_an_unknown_step(client: TestClient) -> None:
    resp = client.post(_LAST_STEP, json={"value": "bogus"})
    assert resp.status_code == 422, resp.text
    assert "bogus" in resp.text


def test_last_step_null_clears_the_resume_point(client: TestClient) -> None:
    client.post(_LAST_STEP, json={"value": "groups"})
    cleared = client.post(_LAST_STEP, json={"value": None})
    assert cleared.status_code == 200, cleared.text
    assert client.get(_LAST_STEP).json() == {"onboarding.last_step": None}


def test_settings_body_carries_both_dotted_keys(client: TestClient) -> None:
    client.post(_COMPLETED, json={"value": _STAMP})
    client.post(_LAST_STEP, json={"value": "places"})
    body = client.get("/api/settings").json()
    assert body["onboarding.completed_at"] == _STAMP
    assert body["onboarding.last_step"] == "places"
    # The merge appends to public(), so nothing secret can ride along with it.
    assert "pin_hash" not in body and "pin_salt" not in body


def test_onboarding_routes_are_locked(locked_client: TestClient) -> None:
    assert locked_client.get(_COMPLETED).status_code == 401
    assert locked_client.post(_COMPLETED, json={"value": _STAMP}).status_code == 401
    assert locked_client.get(_LAST_STEP).status_code == 401
    assert locked_client.post(_LAST_STEP, json={"value": "devices"}).status_code == 401


def test_patch_collection_writes_last_step(client: TestClient) -> None:
    resp = client.patch("/api/settings", json={"onboarding.last_step": "devices"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["onboarding.last_step"] == "devices"
    assert client.get("/api/settings").json()["onboarding.last_step"] == "devices"


def test_patch_collection_rejects_an_unknown_step(client: TestClient) -> None:
    resp = client.patch("/api/settings", json={"onboarding.last_step": "nope"})
    assert resp.status_code == 422, resp.text


def test_patch_collection_clears_completed_at(client: TestClient) -> None:
    client.post(_COMPLETED, json={"value": _STAMP})
    resp = client.patch("/api/settings", json={"onboarding.completed_at": None})
    assert resp.status_code == 200, resp.text
    assert resp.json()["onboarding.completed_at"] is None


def test_empty_patch_leaves_both_untouched(client: TestClient) -> None:
    client.post(_COMPLETED, json={"value": _STAMP})
    client.post(_LAST_STEP, json={"value": "applock"})
    resp = client.patch("/api/settings", json={})
    assert resp.status_code == 200, resp.text
    assert resp.json()["onboarding.completed_at"] == _STAMP
    assert resp.json()["onboarding.last_step"] == "applock"
