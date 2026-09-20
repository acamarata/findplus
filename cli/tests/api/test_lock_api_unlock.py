"""App lock: the unlock flow, its cookie, and session expiry/revocation.

Split from test_lock_api.py (PRI rule 7, 449 lines); see _lock_helpers.py
for the shared client/store fixtures and PIN.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from findplus.security import SessionStore
from tests.api._lock_helpers import PIN, _set_pin, client, store  # noqa: F401


def test_correct_pin_unlocks(client: TestClient) -> None:  # noqa: F811
    _set_pin(client)
    client.cookies.clear()
    res = client.post("/api/lock/unlock", json={"pin": PIN})
    assert res.status_code == 200
    assert res.json()["unlocked"] is True
    assert client.get("/api/status").status_code == 200


def test_wrong_pin_does_not_unlock(client: TestClient) -> None:  # noqa: F811
    _set_pin(client)
    client.cookies.clear()
    assert client.post("/api/lock/unlock", json={"pin": "000000"}).status_code == 401
    assert client.get("/api/status").status_code == 401


def test_unlock_issues_an_httponly_cookie(client: TestClient) -> None:  # noqa: F811
    """HttpOnly keeps the token away from any script running on the page."""
    _set_pin(client)
    client.cookies.clear()
    res = client.post("/api/lock/unlock", json={"pin": PIN})
    header = res.headers["set-cookie"]
    assert "httponly" in header.lower()
    assert "samesite=strict" in header.lower()


def test_manual_lock_revokes_the_session(client: TestClient) -> None:  # noqa: F811
    _set_pin(client)
    client.cookies.clear()
    client.post("/api/lock/unlock", json={"pin": PIN})
    assert client.get("/api/status").status_code == 200

    client.post("/api/lock/lock")
    assert client.get("/api/status").status_code == 401


def test_configured_idle_timeout_reaches_the_session_store(
    client: TestClient,  # noqa: F811
    store: SessionStore,  # noqa: F811
) -> None:
    """The setting must actually drive session expiry, not just be stored.

    Expiry itself is covered directly in test_security.py; this pins the wiring.
    """
    _set_pin(client)
    client.patch("/api/settings", json={"idle_minutes": 5})
    client.get("/api/status")
    assert store.idle_timeout_seconds == 5 * 60

    client.patch("/api/settings", json={"idle_minutes": 0})
    client.get("/api/status")
    assert store.idle_timeout_seconds == 0


def test_an_expired_session_relocks_the_api(client: TestClient, store: SessionStore) -> None:  # noqa: F811
    _set_pin(client)
    client.cookies.clear()
    client.post("/api/lock/unlock", json={"pin": PIN})
    assert client.get("/api/status").status_code == 200

    # Simulate the idle timer firing: the store drops the session.
    store.revoke_all()
    assert client.get("/api/status").status_code == 401
