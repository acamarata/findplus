"""Multi-device timeline and API behaviour.

The central guarantee here: timelines are computed PER DEVICE and never merged
(PROMPT.md §2 invariant 5). Interleaving two trackers would produce distances
and elapsed times that jump between unrelated objects.

Split out of test_multi_device.py, which was 392 lines (PRI hard rule 7 applies
to test files too); that file keeps device SELECTION and POLLING.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from findplus.db.session import session_scope
from findplus.ingest import ingest_observations, upsert_device
from findplus.state import track_devices
from tests.conftest import make_observation

BIKE = ("TAG-BIKE", "Bike Tag")
KEYS = ("TAG-KEYS", "Keys Tag")
BAG = ("TAG-BAG", "Backpack Tag")


# --------------------------------------------------------------- timeline
@pytest.fixture
def two_tracks(tmp_db):
    """Two devices on the same day, in places far apart."""
    with session_scope() as session:
        for device_id, name in (BIKE, KEYS, BAG):
            upsert_device(session, device_id, name, provider="test-multi")
        track_devices(session, [BIKE[0], KEYS[0]], exclusive=True)
        ingest_observations(
            session,
            [
                make_observation(device_id=BIKE[0], device_name=BIKE[1], lat=41.10, minutes=0),
                make_observation(device_id=BIKE[0], device_name=BIKE[1], lat=41.11, minutes=20),
                # ~350 km away — merging would invent an absurd hop.
                make_observation(device_id=KEYS[0], device_name=KEYS[1], lat=44.10, minutes=10),
                make_observation(device_id=KEYS[0], device_name=KEYS[1], lat=44.11, minutes=30),
            ],
            fetched_at=datetime(2026, 9, 18, 13, 0, tzinfo=UTC),
        )
    from findplus.api import create_app

    return TestClient(create_app())


def test_timeline_returns_one_track_per_device(two_tracks: TestClient) -> None:
    body = two_tracks.get("/api/timeline?day=2026-09-18&timezone=UTC").json()
    assert len(body["tracks"]) == 2
    assert {t["device_id"] for t in body["tracks"]} == {BIKE[0], KEYS[0]}
    assert body["total_observations"] == 4


def test_tracks_are_never_merged_across_devices(two_tracks: TestClient) -> None:
    """The guarantee: no distance is ever computed between two different tags."""
    body = two_tracks.get("/api/timeline?day=2026-09-18&timezone=UTC").json()
    for track in body["tracks"]:
        assert track["points"][0]["meters_from_previous"] is None, (
            "each device's timeline must start fresh, not continue from another device"
        )
        for point in track["points"][1:]:
            # Within a device the hops are ~1 km. A merged list would show ~350 km.
            assert point["meters_from_previous"] < 50_000


def test_each_track_has_its_own_statistics(two_tracks: TestClient) -> None:
    body = two_tracks.get("/api/timeline?day=2026-09-18&timezone=UTC").json()
    for track in body["tracks"]:
        assert track["stats"]["observation_count"] == 2
        assert track["stats"]["time_span_seconds"] == 20 * 60


def test_timeline_can_be_filtered_to_one_device(two_tracks: TestClient) -> None:
    body = two_tracks.get(f"/api/timeline?day=2026-09-18&timezone=UTC&device_id={BIKE[0]}").json()
    assert len(body["tracks"]) == 1
    assert body["tracks"][0]["device_id"] == BIKE[0]


# ------------------------------------------------------------------- api
def test_devices_endpoint_reports_rate_and_counts(two_tracks: TestClient) -> None:
    body = two_tracks.get("/api/devices").json()
    assert body["tracked_count"] == 2
    # 2 devices every 5 minutes = 24 requests/hour.
    assert body["requests_per_hour"] == pytest.approx(24.0)
    counts = {d["device_id"]: d["observation_count"] for d in body["devices"]}
    assert counts[BIKE[0]] == 2
    assert counts[BAG[0]] == 0


def test_track_endpoint_replaces_the_tracked_set(two_tracks: TestClient) -> None:
    res = two_tracks.post("/api/devices/track", json={"device_ids": [BAG[0]]})
    assert res.status_code == 200
    assert res.json()["tracked_count"] == 1
    listing = two_tracks.get("/api/devices").json()
    tracked = {d["device_id"] for d in listing["devices"] if d["is_tracked"]}
    assert tracked == {BAG[0]}


def test_track_all_endpoint(two_tracks: TestClient) -> None:
    res = two_tracks.post("/api/devices/track", json={"all_devices": True})
    assert res.json()["tracked_count"] == 3


def test_tracking_nothing_is_allowed(two_tracks: TestClient) -> None:
    res = two_tracks.post("/api/devices/track", json={"device_ids": []})
    assert res.json()["tracked_count"] == 0
    assert res.json()["requests_per_hour"] == 0


def test_status_aggregates_across_devices(two_tracks: TestClient) -> None:
    body = two_tracks.get("/api/status?timezone=UTC").json()
    assert body["observations_total"] == 4
    assert body["tracked_count"] == 2
    assert len(body["devices"]) == 3


def test_status_can_scope_to_one_device(two_tracks: TestClient) -> None:
    body = two_tracks.get(f"/api/status?timezone=UTC&device_id={BIKE[0]}").json()
    assert body["observations_total"] == 2
    assert body["latest_observation"]["device_id"] == BIKE[0]


def test_export_can_be_filtered_by_device(two_tracks: TestClient) -> None:
    import csv
    import io

    from findplus.exporters import csv_table

    everything = list(
        csv.DictReader(io.StringIO(csv_table(two_tracks.get("/api/export?fmt=csv").text)))
    )
    one = list(
        csv.DictReader(
            io.StringIO(csv_table(two_tracks.get(f"/api/export?fmt=csv&device_id={BIKE[0]}").text))
        )
    )
    assert len(everything) == 4
    assert len(one) == 2
    assert {r["device_id"] for r in one} == {BIKE[0]}


def test_export_accepts_a_date_range(two_tracks: TestClient) -> None:
    import csv
    import io

    inside = two_tracks.get("/api/export?fmt=csv&start=2026-09-17&end=2026-09-19&timezone=UTC").text
    outside = two_tracks.get(
        "/api/export?fmt=csv&start=2026-09-01&end=2026-09-02&timezone=UTC"
    ).text
    from findplus.exporters import csv_table

    assert len(list(csv.DictReader(io.StringIO(csv_table(inside))))) == 4
    assert len(list(csv.DictReader(io.StringIO(csv_table(outside))))) == 0


def test_devices_with_data_ignores_devices_that_never_reported(two_tracks: TestClient) -> None:
    body = two_tracks.get("/api/timeline?day=2026-09-18&timezone=UTC").json()
    assert BAG[0] not in {t["device_id"] for t in body["tracks"]}
