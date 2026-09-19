"""App lock, settings and history deletion through the HTTP API.

The load-bearing assertion here: while locked, the SERVER refuses to return
location data. If the lock were only a UI overlay, the history would still be
one `curl` away.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from findplus.appsettings import load_settings
from findplus.db.session import session_scope
from findplus.ingest import ingest_observations, upsert_device
from findplus.security import MAX_ATTEMPTS, SessionStore
from findplus.state import track_devices
from tests.conftest import make_observation

PIN = "8642"

#: Every endpoint that must refuse to answer while locked.
GATED = [
    "/api/status",
    "/api/timeline",
    "/api/days",
    "/api/latest",
    "/api/devices",
    "/api/config",
    "/api/export?fmt=csv",
    "/api/poll-runs",
    "/api/settings",
]


@pytest.fixture
def store() -> SessionStore:
    return SessionStore()


@pytest.fixture
def client(tmp_db, store):
    from findplus.api import create_app

    with session_scope() as session:
        upsert_device(session, "TAG-001", "Moto Tag 2")
        track_devices(session, ["TAG-001"], exclusive=True)
        ingest_observations(
            session,
            [make_observation(minutes=0, lat=41.1), make_observation(minutes=20, lat=41.2)],
            fetched_at=datetime(2026, 9, 18, 13, 0, tzinfo=UTC),
        )
    return TestClient(create_app(store))


def _set_pin(client: TestClient, pin: str = PIN) -> None:
    assert client.post("/api/settings/pin", json={"new_pin": pin}).status_code == 200


# ------------------------------------------------------------ default state
def test_lock_is_off_by_default(client: TestClient) -> None:
    body = client.get("/api/lock/status").json()
    assert body["lock_configured"] is False
    assert body["locked"] is False


def test_everything_is_reachable_when_no_pin_is_set(client: TestClient) -> None:
    for path in GATED:
        assert client.get(path).status_code == 200, path


# ----------------------------------------------------------------- setting up
def test_setting_a_pin_enables_the_lock(client: TestClient) -> None:
    body = client.post("/api/settings/pin", json={"new_pin": PIN}).json()
    assert body["pin_configured"] is True
    assert body["lock_enabled"] is True
    assert body["lock_active"] is True


def test_pin_is_never_returned_by_the_api(client: TestClient) -> None:
    _set_pin(client)
    for path in ("/api/settings", "/api/lock/status"):
        text = client.get(path).text
        assert PIN not in text
        assert "pin_hash" not in text
        assert "pin_salt" not in text


def test_short_pins_are_rejected(client: TestClient) -> None:
    assert client.post("/api/settings/pin", json={"new_pin": "12"}).status_code == 400


def test_pin_is_stored_only_as_a_hash(client: TestClient) -> None:
    _set_pin(client)
    with session_scope() as session:
        stored = load_settings(session)
    assert stored.pin_hash and PIN not in stored.pin_hash
    assert stored.pin_salt and PIN not in stored.pin_salt


# --------------------------------------------------------------- enforcement
def test_locked_api_refuses_every_gated_endpoint(client: TestClient) -> None:
    """The core guarantee: no location data crosses the boundary while locked."""
    _set_pin(client)
    client.cookies.clear()
    for path in GATED:
        res = client.get(path)
        assert res.status_code == 401, f"{path} leaked data while locked"
        assert res.json()["locked"] is True


def test_locked_export_returns_no_coordinates(client: TestClient) -> None:
    _set_pin(client)
    client.cookies.clear()
    res = client.get("/api/export?fmt=csv")
    assert res.status_code == 401
    assert "41.1" not in res.text


def test_lock_status_and_health_stay_reachable_while_locked(client: TestClient) -> None:
    """The client must be able to discover that it is locked."""
    _set_pin(client)
    client.cookies.clear()
    assert client.get("/api/lock/status").status_code == 200
    assert client.get("/api/lock/status").json()["locked"] is True
    assert client.get("/api/health").status_code == 200


def test_shell_page_still_loads_so_the_lock_screen_can_render(client: TestClient) -> None:
    _set_pin(client)
    client.cookies.clear()
    res = client.get("/")
    assert res.status_code == 200
    assert "lock-screen" in res.text


# ---------------------------------------------------------------- unlocking
def test_correct_pin_unlocks(client: TestClient) -> None:
    _set_pin(client)
    client.cookies.clear()
    res = client.post("/api/lock/unlock", json={"pin": PIN})
    assert res.status_code == 200
    assert res.json()["unlocked"] is True
    assert client.get("/api/status").status_code == 200


def test_wrong_pin_does_not_unlock(client: TestClient) -> None:
    _set_pin(client)
    client.cookies.clear()
    assert client.post("/api/lock/unlock", json={"pin": "0000"}).status_code == 401
    assert client.get("/api/status").status_code == 401


def test_unlock_issues_an_httponly_cookie(client: TestClient) -> None:
    """HttpOnly keeps the token away from any script running on the page."""
    _set_pin(client)
    client.cookies.clear()
    res = client.post("/api/lock/unlock", json={"pin": PIN})
    header = res.headers["set-cookie"]
    assert "httponly" in header.lower()
    assert "samesite=strict" in header.lower()


def test_brute_force_is_throttled(client: TestClient) -> None:
    _set_pin(client)
    client.cookies.clear()
    for _ in range(MAX_ATTEMPTS):
        assert client.post("/api/lock/unlock", json={"pin": "0000"}).status_code == 401
    res = client.post("/api/lock/unlock", json={"pin": "0000"})
    assert res.status_code == 429
    assert "Try again in" in res.json()["detail"]


def test_throttling_blocks_even_the_correct_pin(client: TestClient) -> None:
    """Otherwise the lockout could be probed away by guessing."""
    _set_pin(client)
    client.cookies.clear()
    for _ in range(MAX_ATTEMPTS):
        client.post("/api/lock/unlock", json={"pin": "0000"})
    assert client.post("/api/lock/unlock", json={"pin": PIN}).status_code == 429


def test_manual_lock_revokes_the_session(client: TestClient) -> None:
    _set_pin(client)
    client.cookies.clear()
    client.post("/api/lock/unlock", json={"pin": PIN})
    assert client.get("/api/status").status_code == 200

    client.post("/api/lock/lock")
    assert client.get("/api/status").status_code == 401


def test_configured_idle_timeout_reaches_the_session_store(
    client: TestClient, store: SessionStore
) -> None:
    """The setting must actually drive session expiry, not just be stored.

    Expiry itself is covered directly in test_security.py; this pins the wiring.
    """
    _set_pin(client)
    client.put("/api/settings", json={"idle_minutes": 5})
    client.get("/api/status")
    assert store.idle_timeout_seconds == 5 * 60

    client.put("/api/settings", json={"idle_minutes": 0})
    client.get("/api/status")
    assert store.idle_timeout_seconds == 0


def test_an_expired_session_relocks_the_api(client: TestClient, store: SessionStore) -> None:
    _set_pin(client)
    client.cookies.clear()
    client.post("/api/lock/unlock", json={"pin": PIN})
    assert client.get("/api/status").status_code == 200

    # Simulate the idle timer firing: the store drops the session.
    store.revoke_all()
    assert client.get("/api/status").status_code == 401


def test_setting_a_pin_keeps_the_current_browser_signed_in(client: TestClient) -> None:
    """Setting a PIN must not lock you out of the window you set it in."""
    _set_pin(client)
    assert client.get("/api/status").status_code == 200


def test_changing_the_pin_signs_other_sessions_out(client: TestClient, store: SessionStore) -> None:
    _set_pin(client)
    other_token = store.create()  # a second browser, already unlocked

    client.post("/api/settings/pin", json={"new_pin": "1357", "current_pin": PIN})

    assert store.is_valid(other_token) is False, "other devices must be signed out"
    assert client.get("/api/status").status_code == 200, "this browser stays signed in"


def test_the_new_pin_is_the_one_that_works(client: TestClient) -> None:
    _set_pin(client)
    client.post("/api/settings/pin", json={"new_pin": "1357", "current_pin": PIN})
    client.cookies.clear()

    assert client.post("/api/lock/unlock", json={"pin": PIN}).status_code == 401
    assert client.post("/api/lock/unlock", json={"pin": "1357"}).status_code == 200


def test_changing_the_pin_requires_the_current_one(client: TestClient) -> None:
    _set_pin(client)
    res = client.post("/api/settings/pin", json={"new_pin": "1357", "current_pin": "wrong"})
    assert res.status_code == 403


def test_removing_the_pin_requires_it_and_disables_the_lock(client: TestClient) -> None:
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


def test_lock_can_be_disabled_without_removing_the_pin(client: TestClient) -> None:
    _set_pin(client)
    client.put("/api/settings", json={"lock_enabled": False})
    client.cookies.clear()
    assert client.get("/api/status").status_code == 200
    body = client.get("/api/lock/status").json()
    assert body["lock_configured"] is True
    assert body["locked"] is False


def test_lock_cannot_be_enabled_without_a_pin(client: TestClient) -> None:
    res = client.put("/api/settings", json={"lock_enabled": True})
    assert res.status_code == 400
    assert "Set a PIN" in res.json()["detail"]


def test_requirements_endpoint_states_the_caveat_honestly(client: TestClient) -> None:
    body = client.get("/api/lock/requirements").json()
    assert body["min_pin_length"] == 4
    assert "does NOT encrypt" in body["caveat"] or "NOT encrypt" in body["caveat"]


# ----------------------------------------------------------------- settings
def test_theme_round_trips(client: TestClient) -> None:
    assert client.get("/api/settings").json()["theme"] == "dark"
    assert client.put("/api/settings", json={"theme": "light"}).json()["theme"] == "light"
    assert client.get("/api/settings").json()["theme"] == "light"


def test_unknown_theme_rejected(client: TestClient) -> None:
    assert client.put("/api/settings", json={"theme": "neon"}).status_code == 400


def test_idle_timeout_round_trips(client: TestClient) -> None:
    assert client.put("/api/settings", json={"idle_minutes": 5}).json()["idle_minutes"] == 5


def test_idle_timeout_zero_means_never(client: TestClient) -> None:
    assert client.put("/api/settings", json={"idle_minutes": 0}).json()["idle_minutes"] == 0


def test_absurd_idle_timeout_rejected(client: TestClient) -> None:
    assert client.put("/api/settings", json={"idle_minutes": 99999}).status_code == 400


# ---------------------------------------------------------- clear history
def test_clear_history_is_a_dry_run_without_confirmation(client: TestClient) -> None:
    body = client.post("/api/history/clear", json={}).json()
    assert body["deleted"] == 0
    assert body["would_delete"] == 2
    assert client.get("/api/status?timezone=UTC").json()["observations_total"] == 2


def test_clear_history_deletes_everything_when_confirmed(client: TestClient) -> None:
    body = client.post("/api/history/clear", json={"confirm": True}).json()
    assert body["deleted"] == 2
    assert client.get("/api/status?timezone=UTC").json()["observations_total"] == 0


def test_clear_history_can_target_one_device(client: TestClient) -> None:
    with session_scope() as session:
        upsert_device(session, "TAG-OTHER", "Keys")
        ingest_observations(
            session, [make_observation(device_id="TAG-OTHER", device_name="Keys", lat=42.0)]
        )
    body = client.post("/api/history/clear", json={"confirm": True, "device_id": "TAG-001"}).json()
    assert body["deleted"] == 2
    assert client.get("/api/status?timezone=UTC").json()["observations_total"] == 1


def test_history_clear_cascades_place_events(client: TestClient) -> None:
    """A place_event anchored to a cleared observation is deleted, not orphaned."""
    from sqlalchemy import func, select

    from findplus.db.models import LocationObservation, Place, PlaceEvent

    with session_scope() as session:
        obs = session.scalars(
            select(LocationObservation).order_by(LocationObservation.observed_at)
        ).first()
        place = Place(
            name="P1",
            latitude_e7=411000000,
            longitude_e7=-806400000,
            radius_meters=100,
            color="#2f80ed",
            enter_confirmations=1,
            exit_confirmations=2,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(place)
        session.flush()
        session.add(
            PlaceEvent(
                place_id=place.id,
                device_id="TAG-001",
                event_type="ENTER",
                observed_at=obs.observed_at,
                fetched_at=obs.last_fetched_at,
                observation_id=obs.id,
                confidence="high",
                distance_meters=42.0,
            )
        )

    body = client.post("/api/history/clear", json={"confirm": True}).json()
    assert body["deleted"] == 2

    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(PlaceEvent)) == 0


def test_clear_history_is_gated_by_the_lock(client: TestClient) -> None:
    _set_pin(client)
    client.cookies.clear()
    assert client.post("/api/history/clear", json={"confirm": True}).status_code == 401
    assert client.get("/api/lock/status").json()["locked"] is True


# ------------------------------------------------------- recovery from lockout
def test_reset_lock_cli_clears_a_forgotten_pin(client: TestClient) -> None:
    """The only PIN recovery path, and it requires local filesystem access."""
    from click.testing import CliRunner

    from findplus.cli.main import main

    _set_pin(client)
    client.cookies.clear()
    assert client.get("/api/status").status_code == 401

    result = CliRunner().invoke(main, ["reset-lock", "--yes"])
    assert result.exit_code == 0, result.output

    with session_scope() as session:
        assert load_settings(session).pin_configured is False
    assert client.get("/api/status").status_code == 200


def test_reset_lock_is_harmless_when_no_pin_is_set(tmp_db) -> None:
    from click.testing import CliRunner

    from findplus.cli.main import main

    result = CliRunner().invoke(main, ["reset-lock", "--yes"])
    assert result.exit_code == 0
    assert "nothing to reset" in result.output.lower()
