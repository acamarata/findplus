"""App lock: setting, changing, removing and padding-rejecting the PIN.

Split from test_lock_api.py (PRI rule 7, 449 lines); see _lock_helpers.py
for the shared client/store fixtures and PIN.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from findplus import honesty
from findplus.appsettings import load_settings
from findplus.db.session import session_scope
from findplus.security import SessionStore
from tests.api._lock_helpers import PIN, _set_pin, client, store  # noqa: F401


# ----------------------------------------------------------------- setting up
def test_setting_a_pin_enables_the_lock(client: TestClient) -> None:  # noqa: F811
    body = client.post("/api/settings/pin", json={"new_pin": PIN}).json()
    assert body["pin_configured"] is True
    assert body["lock_enabled"] is True
    assert body["lock_active"] is True


def test_pin_is_never_returned_by_the_api(client: TestClient) -> None:  # noqa: F811
    _set_pin(client)
    for path in ("/api/settings", "/api/lock/status"):
        text = client.get(path).text
        assert PIN not in text
        assert "pin_hash" not in text
        assert "pin_salt" not in text


def test_short_pins_are_rejected(client: TestClient) -> None:  # noqa: F811
    assert client.post("/api/settings/pin", json={"new_pin": "12"}).status_code == 400


def test_pin_is_stored_only_as_a_hash(client: TestClient) -> None:  # noqa: F811
    _set_pin(client)
    with session_scope() as session:
        stored = load_settings(session)
    assert stored.pin_hash and PIN not in stored.pin_hash
    assert stored.pin_salt and PIN not in stored.pin_salt


# ---------------------------------------------------------- changing/removing
def test_setting_a_pin_keeps_the_current_browser_signed_in(client: TestClient) -> None:  # noqa: F811
    """Setting a PIN must not lock you out of the window you set it in."""
    _set_pin(client)
    assert client.get("/api/status").status_code == 200


def test_changing_the_pin_signs_other_sessions_out(client: TestClient, store: SessionStore) -> None:  # noqa: F811
    _set_pin(client)
    other_token = store.create()  # a second browser, already unlocked

    client.post("/api/settings/pin", json={"new_pin": "135792", "current_pin": PIN})

    assert store.is_valid(other_token) is False, "other devices must be signed out"
    assert client.get("/api/status").status_code == 200, "this browser stays signed in"


def test_the_new_pin_is_the_one_that_works(client: TestClient) -> None:  # noqa: F811
    _set_pin(client)
    client.post("/api/settings/pin", json={"new_pin": "135792", "current_pin": PIN})
    client.cookies.clear()

    assert client.post("/api/lock/unlock", json={"pin": PIN}).status_code == 401
    assert client.post("/api/lock/unlock", json={"pin": "135792"}).status_code == 200


def test_changing_the_pin_requires_the_current_one(client: TestClient) -> None:  # noqa: F811
    _set_pin(client)
    res = client.post("/api/settings/pin", json={"new_pin": "135792", "current_pin": "wrong"})
    assert res.status_code == 403


def test_removing_the_pin_requires_it_and_disables_the_lock(client: TestClient) -> None:  # noqa: F811
    _set_pin(client)
    assert (
        client.request("DELETE", "/api/settings/pin", json={"current_pin": "wrong"}).status_code
        == 403
    )

    res = client.request("DELETE", "/api/settings/pin", json={"current_pin": PIN})
    assert res.status_code == 200
    assert res.json()["pin_configured"] is False
    client.cookies.clear()
    assert client.get("/api/status").status_code == 200


def test_lock_can_be_disabled_without_removing_the_pin(client: TestClient) -> None:  # noqa: F811
    _set_pin(client)
    client.patch("/api/settings", json={"lock_enabled": False})
    client.cookies.clear()
    assert client.get("/api/status").status_code == 200
    body = client.get("/api/lock/status").json()
    assert body["lock_configured"] is True
    assert body["locked"] is False


def test_lock_cannot_be_enabled_without_a_pin(client: TestClient) -> None:  # noqa: F811
    res = client.patch("/api/settings", json={"lock_enabled": True})
    assert res.status_code == 400
    assert "Set a PIN" in res.json()["detail"]


def test_requirements_endpoint_states_the_caveat_honestly(client: TestClient) -> None:  # noqa: F811
    body = client.get("/api/lock/requirements").json()
    assert body["min_pin_length"] == 6
    # The verbatim specs/honesty.md sentence — the route used to serve its own
    # paraphrase, which the Settings dialog showed beside the canonical one.
    assert body["caveat"] == honesty.LOCK_NOT_ENCRYPTION


# ------------------------------------------------ padded-PIN rejection (F4)
def test_setting_a_padded_pin_is_rejected(client: TestClient) -> None:  # noqa: F811
    assert client.post("/api/settings/pin", json={"new_pin": PIN + " "}).status_code == 422
    assert client.post("/api/settings/pin", json={"new_pin": " " + PIN}).status_code == 422


def test_changing_the_pin_rejects_a_padded_current_or_new_pin(client: TestClient) -> None:  # noqa: F811
    _set_pin(client)
    res = client.post("/api/settings/pin", json={"new_pin": " 135792", "current_pin": PIN})
    assert res.status_code == 422
    res = client.post("/api/settings/pin", json={"new_pin": "135792", "current_pin": PIN + " "})
    assert res.status_code == 422


def test_removing_the_pin_rejects_a_padded_current_pin(client: TestClient) -> None:  # noqa: F811
    _set_pin(client)
    res = client.request("DELETE", "/api/settings/pin", json={"current_pin": PIN + " "})
    assert res.status_code == 422


def test_unlock_rejects_a_padded_pin_even_when_it_would_match_trimmed(client: TestClient) -> None:  # noqa: F811
    """A padded PIN was never stored (set is rejected too), but a foreign page or a
    stale client could still submit one directly -- it must never be treated as a
    wrong-PIN guess (which would burn a brute-force attempt) nor as a match."""
    _set_pin(client)
    client.cookies.clear()
    res = client.post("/api/lock/unlock", json={"pin": PIN + " "})
    assert res.status_code == 422
    # The rejection must not have consumed a brute-force attempt.
    assert client.post("/api/lock/unlock", json={"pin": PIN}).status_code == 200
