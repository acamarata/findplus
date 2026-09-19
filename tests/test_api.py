"""Local API contract: shapes, privacy posture, exports and safe deletion."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient

from bike_tracker.db.session import session_scope
from bike_tracker.ingest import ingest_observations, upsert_device
from bike_tracker.state import track_devices
from tests.conftest import make_observation


@pytest.fixture
def client(tmp_db):
    from bike_tracker.api import create_app

    with session_scope() as session:
        upsert_device(session, "TAG-001", "Moto Tag 2")
        track_devices(session, ["TAG-001"], exclusive=True)
        ingest_observations(
            session,
            [
                make_observation(minutes=0, lat=41.100),
                make_observation(minutes=17, lat=41.110),
                make_observation(minutes=63, lat=41.140),  # 46-minute gap
            ],
            fetched_at=datetime(2026, 9, 18, 13, 5, tzinfo=UTC),
        )
    return TestClient(create_app())


def test_health_reports_schema_state(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["schema_up_to_date"] is True


def test_config_exposes_thresholds_and_the_findhub_notice(client: TestClient) -> None:
    body = client.get("/api/config").json()
    assert body["poll_interval_minutes"] >= 5
    assert body["movement_threshold_meters"] == 25.0
    assert "should not be treated as real-time emergency" in body["notice"]


def test_config_never_leaks_secret_values(client: TestClient) -> None:
    """The auth block must describe WHICH material is stored, never the values."""
    auth = client.get("/api/config").json()["auth"]
    assert set(auth) == {"path", "exists", "permissions", "keys_present"}
    assert "aas_token" not in str(auth.get("permissions"))
    blob = client.get("/api/config").text
    for leak in ("aas_et", "ya29.", "oauth2_4"):
        assert leak not in blob


def test_status_separates_observed_from_retrieved(client: TestClient) -> None:
    latest = client.get("/api/status").json()["latest_observation"]
    assert latest["observed_at_utc"] != latest["fetched_at_utc"]
    assert latest["retrieval_lag_seconds"] > 0
    assert latest["age_seconds"] > 0


def test_status_counts_todays_observations(client: TestClient) -> None:
    body = client.get("/api/status?timezone=UTC").json()
    assert body["observations_total"] == 3
    assert body["devices"][0]["name"] == "Moto Tag 2"


def test_timeline_returns_ordered_annotated_points(client: TestClient) -> None:
    body = client.get("/api/timeline?day=2026-09-18&timezone=UTC").json()
    assert len(body["tracks"]) == 1
    points = body["tracks"][0]["points"]
    assert [p["sequence"] for p in points] == [1, 2, 3]
    assert points[0]["meters_from_previous"] is None
    assert points[1]["meters_from_previous"] > 0
    assert "actual route between detections may differ" in body["path_disclaimer"]


def test_timeline_flags_the_gap(client: TestClient) -> None:
    points = client.get("/api/timeline?day=2026-09-18&timezone=UTC").json()["tracks"][0]["points"]
    assert points[1]["gap_before"] is False
    assert points[2]["gap_before"] is True
    assert points[2]["seconds_since_previous"] == 46 * 60


def test_timeline_thresholds_are_overridable_per_request(client: TestClient) -> None:
    loose = client.get(
        "/api/timeline?day=2026-09-18&timezone=UTC&movement_threshold_meters=100000"
    ).json()
    assert all(p["is_movement"] is False for p in loose["tracks"][0]["points"][1:])


def test_timeline_stats_label_distance_as_approximate(client: TestClient) -> None:
    stats = client.get("/api/timeline?day=2026-09-18&timezone=UTC").json()["tracks"][0]["stats"]
    assert stats["observation_count"] == 3
    assert stats["longest_gap_seconds"] == 46 * 60
    assert stats["distance_label"] == "Approximate distance between observed locations"


def test_empty_day_returns_an_empty_timeline_not_an_error(client: TestClient) -> None:
    body = client.get("/api/timeline?day=2020-01-01&timezone=UTC").json()
    assert body["tracks"] == []
    assert body["total_observations"] == 0


def test_invalid_date_is_rejected(client: TestClient) -> None:
    assert client.get("/api/timeline?day=not-a-date").status_code == 400


def test_days_lists_only_days_with_data(client: TestClient) -> None:
    assert client.get("/api/days?timezone=UTC").json()["days"] == ["2026-09-18"]


def test_latest_endpoint_reads_history_without_querying_google(client: TestClient) -> None:
    body = client.get("/api/latest?timezone=UTC").json()
    assert body["latitude"] == pytest.approx(41.140)
    assert "fetched_at_local" in body and "observed_at_local" in body


def test_devices_endpoint_reports_tracking_state(client: TestClient) -> None:
    body = client.get("/api/devices").json()
    assert body["tracked_count"] == 1
    assert body["devices"][0]["is_tracked"] is True
    assert body["devices"][0]["observation_count"] == 3


def test_tracking_an_unknown_device_is_a_404(client: TestClient) -> None:
    res = client.post("/api/devices/track", json={"device_ids": ["NOPE"]})
    assert res.status_code == 404


# ---------------------------------------------------------------- exports
def test_csv_export_downloads_with_a_filename(client: TestClient) -> None:
    res = client.get("/api/export?fmt=csv&day=2026-09-18&timezone=UTC")
    assert res.status_code == 200
    assert "attachment" in res.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(res.text)))
    assert len(rows) == 3


def test_gpx_export_is_valid_xml_with_trackpoints(client: TestClient) -> None:
    res = client.get("/api/export?fmt=gpx&day=2026-09-18&timezone=UTC")
    root = ElementTree.fromstring(res.text)
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    assert len(root.findall(".//g:trkpt", ns)) == 3


@pytest.mark.parametrize("fmt", ["csv", "json", "gpx", "kml"])
def test_all_export_formats_respond(client: TestClient, fmt: str) -> None:
    assert client.get(f"/api/export?fmt={fmt}&day=2026-09-18&timezone=UTC").status_code == 200


def test_export_all_history_works(client: TestClient) -> None:
    rows = list(csv.DictReader(io.StringIO(client.get("/api/export?fmt=csv").text)))
    assert len(rows) == 3


def test_export_rejects_unknown_formats(client: TestClient) -> None:
    assert client.get("/api/export?fmt=shapefile").status_code == 422


# -------------------------------------------------------------- retention
def test_delete_before_is_a_dry_run_without_confirmation(client: TestClient) -> None:
    res = client.post("/api/history/delete-before", json={"before": "2026-09-19"})
    body = res.json()
    assert body["deleted"] == 0
    assert body["would_delete"] == 3
    assert client.get("/api/status?timezone=UTC").json()["observations_total"] == 3


def test_delete_before_removes_only_older_rows_when_confirmed(client: TestClient) -> None:
    res = client.post("/api/history/delete-before", json={"before": "2026-09-19", "confirm": True})
    assert res.json()["deleted"] == 3
    assert client.get("/api/status?timezone=UTC").json()["observations_total"] == 0


def test_delete_before_keeps_newer_history(client: TestClient) -> None:
    res = client.post("/api/history/delete-before", json={"before": "2026-09-18", "confirm": True})
    assert res.json()["deleted"] == 0
    assert client.get("/api/status?timezone=UTC").json()["observations_total"] == 3


# ---------------------------------------------------------------- privacy
def test_manual_poll_is_rate_limited(client: TestClient, monkeypatch) -> None:
    import bike_tracker.api as api_module
    import bike_tracker.poller as poller_module

    monkeypatch.setattr(api_module, "_last_manual_poll", None)
    monkeypatch.setattr(
        poller_module,
        "poll_once",
        lambda *a, **k: poller_module.CycleOutcome(
            [poller_module.PollOutcome(status="no_location", device_id="TAG-001")]
        ),
    )
    assert client.post("/api/poll-now").status_code == 200
    assert client.post("/api/poll-now").status_code == 429


def test_dashboard_page_has_no_third_party_scripts(client: TestClient) -> None:
    html = client.get("/").text
    assert "googletagmanager" not in html
    assert "google-analytics" not in html
    for src in ("/static/vendor/leaflet/leaflet.js", "/static/app.js"):
        assert src in html
    # Every script tag must be same-origin.
    import re

    for match in re.findall(r'<script[^>]*src="([^"]+)"', html):
        assert match.startswith("/static/"), f"third-party script: {match}"


def test_dashboard_shows_the_findhub_limitation_notice(client: TestClient) -> None:
    assert "findhub-notice" in client.get("/").text
    assert (
        "should not be treated as real-time emergency" in client.get("/api/config").json()["notice"]
    )
