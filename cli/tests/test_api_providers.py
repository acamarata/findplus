"""GET /api/providers and the devices response's new `provider` field."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_db):
    from findplus.api import create_app

    return TestClient(create_app())


def test_get_providers_returns_list(client: TestClient) -> None:
    resp = client.get("/api/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    required_keys = (
        "name",
        "display_name",
        "available",
        "reason",
        "authenticated",
        "account",
        "limits",
    )
    for item in data:
        for key in required_keys:
            assert key in item, f"missing key {key!r}"


def test_devices_response_has_provider(client: TestClient) -> None:
    resp = client.get("/api/devices")
    assert resp.status_code in (200, 401)
    if resp.status_code == 200:
        for device in resp.json()["devices"]:
            assert "provider" in device


def test_providers_route_is_locked_while_the_app_lock_is_on(client: TestClient) -> None:
    """/api/providers is not in _PUBLIC (api-contract.md): it must 401 while locked."""
    resp = client.post("/api/settings/pin", json={"new_pin": "123456"})
    assert resp.status_code == 200
    assert resp.json()["lock_active"] is True

    # `client` set the PIN, so it already holds the session cookie the settings
    # route re-issues to the caller. Check the locked state with a fresh,
    # cookie-less client instead of the one that just unlocked itself.
    anonymous = TestClient(client.app)
    locked_resp = anonymous.get("/api/providers")
    assert locked_resp.status_code == 401
