"""App lock: public reachability and the gated-endpoint guard.

The load-bearing assertion here: while locked, the SERVER refuses to return
location data. If the lock were only a UI overlay, the history would still be
one `curl` away. Split from test_lock_api.py (PRI rule 7, 449 lines); see
_lock_helpers.py for the shared client/store fixtures and PIN/GATED.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.api._lock_helpers import GATED, _set_pin, client, store  # noqa: F401


# ------------------------------------------------------------ default state
def test_lock_is_off_by_default(client: TestClient) -> None:  # noqa: F811
    body = client.get("/api/lock/status").json()
    assert body["lock_configured"] is False
    assert body["locked"] is False


def test_everything_is_reachable_when_no_pin_is_set(client: TestClient) -> None:  # noqa: F811
    for path in GATED:
        assert client.get(path).status_code == 200, path


# ----------------------------------------------------------------- enforcement
def test_locked_api_refuses_every_gated_endpoint(client: TestClient) -> None:  # noqa: F811
    """The core guarantee: no location data crosses the boundary while locked."""
    _set_pin(client)
    client.cookies.clear()
    for path in GATED:
        res = client.get(path)
        assert res.status_code == 401, f"{path} leaked data while locked"
        assert res.json()["locked"] is True


def test_locked_export_returns_no_coordinates(client: TestClient) -> None:  # noqa: F811
    _set_pin(client)
    client.cookies.clear()
    res = client.get("/api/export?fmt=csv")
    assert res.status_code == 401
    assert "41.1" not in res.text


def test_lock_status_and_health_stay_reachable_while_locked(client: TestClient) -> None:  # noqa: F811
    """The client must be able to discover that it is locked."""
    _set_pin(client)
    client.cookies.clear()
    assert client.get("/api/lock/status").status_code == 200
    assert client.get("/api/lock/status").json()["locked"] is True
    assert client.get("/api/health").status_code == 200


def test_shell_page_still_loads_so_the_lock_screen_can_render(client: TestClient) -> None:  # noqa: F811
    _set_pin(client)
    client.cookies.clear()
    res = client.get("/")
    assert res.status_code == 200
    assert "lock-screen" in res.text


def test_clear_history_is_gated_by_the_lock(client: TestClient) -> None:  # noqa: F811
    _set_pin(client)
    client.cookies.clear()
    assert client.post("/api/history/clear", json={"confirm": True}).status_code == 401
    assert client.get("/api/lock/status").json()["locked"] is True
