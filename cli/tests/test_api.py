"""Local API contract: health, config, status, timeline, devices, privacy.

The export and retention endpoints are covered in test_api_exports.py (split
under PRI rule 7); both share the seeded fixtures in _api_client.py."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


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


def test_timeline_labels_a_point_inside_a_saved_place(client: TestClient) -> None:
    """U30b: a fix inside a saved place gets that place's name; others get None."""
    res = client.post(
        "/api/places",
        json={"name": "Home", "latitude": 41.100, "longitude": -80.123456, "radius_meters": 50},
    )
    assert res.status_code == 201, res.text
    points = client.get("/api/timeline?day=2026-09-18&timezone=UTC").json()["tracks"][0]["points"]
    assert points[0]["place_name"] == "Home"
    assert points[1]["place_name"] is None
    assert points[2]["place_name"] is None
    # Coordinates stay on the point even when a place_name is present, for hover.
    assert points[0]["latitude"] == pytest.approx(41.100)


def test_timeline_place_name_is_none_with_no_saved_places(client: TestClient) -> None:
    points = client.get("/api/timeline?day=2026-09-18&timezone=UTC").json()["tracks"][0]["points"]
    assert all(p["place_name"] is None for p in points)


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


def test_devices_endpoint_carries_groups_and_presence(client: TestClient) -> None:
    """api-contract.md § /api/devices pins both keys; neither was emitted (E1 CR-C).

    Every consumer had to call /api/groups and /api/places/presence itself. The
    keys are additive, so a device in no group and inside no place reports two
    empty lists rather than being omitted.
    """
    row = client.get("/api/devices").json()["devices"][0]

    assert row["groups"] == []
    assert row["presence"] == []


def test_tracking_an_unknown_device_is_a_404(client: TestClient) -> None:
    res = client.post("/api/devices/track", json={"device_ids": ["NOPE"]})
    assert res.status_code == 404


# ---------------------------------------------------------------- exports


# -------------------------------------------------------------- retention


# ---------------------------------------------------------------- privacy
def test_manual_poll_is_rate_limited(client: TestClient, monkeypatch) -> None:
    import findplus.api as api_module
    import findplus.poller as poller_module

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
    for src in ("/static/vendor/leaflet/leaflet.js", "/static/app/main.js"):
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
