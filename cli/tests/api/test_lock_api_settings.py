"""App settings (theme, idle timeout) and history-clear endpoints.

Split from test_lock_api.py (PRI rule 7, 449 lines); the gated-while-locked
case for /api/history/clear lives in test_lock_api_guards.py alongside the
rest of the locked-endpoint sweep. See _lock_helpers.py for the shared
client fixture.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from findplus.db.session import session_scope
from findplus.ingest import ingest_observations, upsert_device
from tests.api._lock_helpers import client, store  # noqa: F401
from tests.conftest import make_observation


# ----------------------------------------------------------------- settings
def test_theme_round_trips(client: TestClient) -> None:  # noqa: F811
    assert client.get("/api/settings").json()["theme"] == "dark"
    assert client.patch("/api/settings", json={"theme": "light"}).json()["theme"] == "light"
    assert client.get("/api/settings").json()["theme"] == "light"


def test_unknown_theme_rejected(client: TestClient) -> None:  # noqa: F811
    assert client.patch("/api/settings", json={"theme": "neon"}).status_code == 400


def test_idle_timeout_round_trips(client: TestClient) -> None:  # noqa: F811
    assert client.patch("/api/settings", json={"idle_minutes": 5}).json()["idle_minutes"] == 5


def test_idle_timeout_zero_means_never(client: TestClient) -> None:  # noqa: F811
    assert client.patch("/api/settings", json={"idle_minutes": 0}).json()["idle_minutes"] == 0


def test_absurd_idle_timeout_rejected(client: TestClient) -> None:  # noqa: F811
    assert client.patch("/api/settings", json={"idle_minutes": 99999}).status_code == 400


def test_put_returns_405_now_that_the_route_is_patch_only(client: TestClient) -> None:  # noqa: F811
    assert client.put("/api/settings", json={"theme": "light"}).status_code == 405


# ------------------------------------------------ poll interval / retention
def _config_env() -> str:
    from findplus.config import get_settings

    path = get_settings().state_dir / "config.env"
    return path.read_text() if path.exists() else ""


def test_poll_interval_round_trips(client: TestClient) -> None:  # noqa: F811
    res = client.patch("/api/settings", json={"poll.interval_minutes": 10})

    assert res.status_code == 200, res.text
    assert res.json()["poll.interval_minutes"] == 10
    assert "POLL_INTERVAL_MINUTES=10" in _config_env()


def test_poll_interval_below_five_is_422(client: TestClient) -> None:  # noqa: F811
    res = client.patch("/api/settings", json={"poll.interval_minutes": 3})

    assert res.status_code == 422
    assert res.json()["detail"] == "poll.interval_minutes must be between 5 and 1440."
    assert "POLL_INTERVAL_MINUTES" not in _config_env()


def test_poll_interval_above_a_day_is_422(client: TestClient) -> None:  # noqa: F811
    res = client.patch("/api/settings", json={"poll.interval_minutes": 2000})

    assert res.status_code == 422
    assert res.json()["detail"] == "poll.interval_minutes must be between 5 and 1440."


def test_retention_days_round_trips(client: TestClient) -> None:  # noqa: F811
    res = client.patch("/api/settings", json={"history.retention_days": 30})

    assert res.status_code == 200, res.text
    assert res.json()["history.retention_days"] == 30
    assert "RETENTION_DAYS=30" in _config_env()


def test_retention_days_below_seven_is_422(client: TestClient) -> None:  # noqa: F811
    res = client.patch("/api/settings", json={"history.retention_days": 3})

    assert res.status_code == 422
    assert res.json()["detail"] == (
        "history.retention_days must be null (keep forever) or at least 7."
    )


def test_retention_null_writes_zero_and_reads_back_null(client: TestClient) -> None:  # noqa: F811
    assert client.patch("/api/settings", json={"history.retention_days": 30}).status_code == 200

    res = client.patch("/api/settings", json={"history.retention_days": None})

    assert res.status_code == 200, res.text
    assert res.json()["history.retention_days"] is None
    assert "RETENTION_DAYS=0" in _config_env()
    assert client.get("/api/settings").json()["history.retention_days"] is None


def test_an_omitted_retention_field_is_left_alone(client: TestClient) -> None:  # noqa: F811
    client.patch("/api/settings", json={"history.retention_days": 30})

    client.patch("/api/settings", json={"theme": "light"})

    assert "RETENTION_DAYS=30" in _config_env()


def test_one_bad_field_writes_neither(client: TestClient) -> None:  # noqa: F811
    res = client.patch(
        "/api/settings",
        json={"poll.interval_minutes": 10, "history.retention_days": 3},
    )

    assert res.status_code == 422
    assert "POLL_INTERVAL_MINUTES" not in _config_env()
    assert "RETENTION_DAYS" not in _config_env()


def test_writing_a_config_field_keeps_the_other_keys(client: TestClient) -> None:  # noqa: F811
    from findplus.config import get_settings, write_config_key

    write_config_key(get_settings(), "LOG_LEVEL", "DEBUG")

    client.patch("/api/settings", json={"poll.interval_minutes": 15})

    env = _config_env()
    assert "LOG_LEVEL=DEBUG" in env
    assert "POLL_INTERVAL_MINUTES=15" in env


# ----------------------------------------------------- alerts.native_detail
def test_native_detail_defaults_to_false(client: TestClient) -> None:  # noqa: F811
    assert client.get("/api/settings").json()["alerts.native_detail"] is False


def test_native_detail_round_trips_through_the_settings_table(client: TestClient) -> None:  # noqa: F811
    res = client.patch("/api/settings", json={"alerts.native_detail": True})

    assert res.status_code == 200, res.text
    assert res.json()["alerts.native_detail"] is True
    assert client.get("/api/settings").json()["alerts.native_detail"] is True
    assert "NATIVE_DETAIL" not in _config_env()

    from findplus.db.session import session_scope as _scope
    from findplus.state import get_setting

    with _scope() as session:
        assert get_setting(session, "alerts.native_detail") == "1"


# ---------------------------------------------------------- clear history
def test_clear_history_is_a_dry_run_without_confirmation(client: TestClient) -> None:  # noqa: F811
    body = client.post("/api/history/clear", json={}).json()
    assert body["deleted"] == 0
    assert body["would_delete"] == 2
    assert client.get("/api/status?timezone=UTC").json()["observations_total"] == 2


def test_clear_history_deletes_everything_when_confirmed(client: TestClient) -> None:  # noqa: F811
    body = client.post("/api/history/clear", json={"confirm": True}).json()
    assert body["deleted"] == 2
    assert client.get("/api/status?timezone=UTC").json()["observations_total"] == 0


def test_clear_history_can_target_one_device(client: TestClient) -> None:  # noqa: F811
    with session_scope() as session:
        upsert_device(session, "TAG-OTHER", "Keys")
        ingest_observations(
            session, [make_observation(device_id="TAG-OTHER", device_name="Keys", lat=42.0)]
        )
    body = client.post("/api/history/clear", json={"confirm": True, "device_id": "TAG-001"}).json()
    assert body["deleted"] == 2
    assert client.get("/api/status?timezone=UTC").json()["observations_total"] == 1


def test_history_clear_cascades_place_events(client: TestClient) -> None:  # noqa: F811
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
