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
    # E3 review carry-forward #24: the key-shape assertions used to sit inside a
    # loop over a possibly-empty list, so they passed vacuously if the
    # `findplus.providers` entry point ever failed to register.
    assert "google-find-hub" in {item["name"] for item in data}
    for item in data:
        for key in required_keys:
            assert key in item, f"missing key {key!r}"


def test_limits_are_per_provider_not_a_constant(client: TestClient) -> None:
    """E11 review (build-notes carry-forward #21): `limits` described every
    provider with one hardcoded sentence; it now comes from the provider."""
    data = client.get("/api/providers").json()
    limits = {item["name"]: item["limits"] for item in data}
    assert limits, "no providers registered"
    assert all(value for value in limits.values())
    if "apple-find-my" in limits:
        assert "Fetch-on-demand" in limits["apple-find-my"]
    if "google-find-hub" in limits:
        assert limits["google-find-hub"] != limits.get("apple-find-my")


def test_devices_response_has_provider(client: TestClient) -> None:
    """E3 review carry-forward #24: this accepted a 401 and looped over a
    possibly-empty list, so it asserted nothing. Seed one device and require a
    200 with the `provider` field actually present."""
    from findplus.db.session import session_scope
    from findplus.ingest import upsert_device

    with session_scope() as session:
        upsert_device(session, "dev-1", "Test tracker")

    resp = client.get("/api/devices")
    assert resp.status_code == 200, resp.text
    devices = resp.json()["devices"]
    assert devices, "seeded device missing from the response"
    for device in devices:
        assert device["provider"] == "google-find-hub"


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
