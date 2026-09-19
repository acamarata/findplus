"""Tracking many devices at once.

The central guarantee here: timelines are computed PER DEVICE and never merged.
Interleaving two trackers would produce distances and elapsed times that jump
between unrelated objects.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from findplus.db.models import LocationObservation, PollRun
from findplus.db.session import session_scope
from findplus.ingest import ingest_observations, upsert_device
from findplus.poller import poll_once
from findplus.state import (
    get_default_device,
    get_tracked_devices,
    set_default_device,
    track_all,
    track_devices,
    untrack_devices,
)
from tests.conftest import make_observation

BIKE = ("TAG-BIKE", "Bike Tag")
KEYS = ("TAG-KEYS", "Keys Tag")
BAG = ("TAG-BAG", "Backpack Tag")


@pytest.fixture
def three_devices(tmp_db):
    with session_scope() as session:
        for device_id, name in (BIKE, KEYS, BAG):
            upsert_device(session, device_id, name, provider="test-multi")
    return [BIKE, KEYS, BAG]


@pytest.fixture
def register_provider(monkeypatch: pytest.MonkeyPatch):
    """Inject a fake provider into the registry, undone automatically after the test."""

    def _register(name: str, provider) -> None:
        from findplus.providers import base

        monkeypatch.setitem(base._REGISTRY, name, provider)

    return _register


# ------------------------------------------------------------- selection
def test_track_all_tracks_every_device(three_devices) -> None:
    with session_scope() as session:
        track_all(session)
        assert len(get_tracked_devices(session)) == 3


def test_track_specific_devices_exclusively(three_devices) -> None:
    with session_scope() as session:
        track_all(session)
        track_devices(session, [BIKE[0], KEYS[0]], exclusive=True)
        tracked = {d.device_id for d in get_tracked_devices(session)}
        assert tracked == {BIKE[0], KEYS[0]}


def test_track_without_exclusive_adds_to_the_set(three_devices) -> None:
    with session_scope() as session:
        track_devices(session, [BIKE[0]], exclusive=True)
        track_devices(session, [KEYS[0]])
        assert len(get_tracked_devices(session)) == 2


def test_untracking_keeps_history(three_devices) -> None:
    with session_scope() as session:
        track_all(session)
        ingest_observations(session, [make_observation(device_id=BIKE[0], device_name=BIKE[1])])
        untrack_devices(session, [BIKE[0]])

        assert BIKE[0] not in {d.device_id for d in get_tracked_devices(session)}
        surviving = session.scalar(
            select(LocationObservation).where(LocationObservation.device_id == BIKE[0])
        )
        assert surviving is not None, "untracking must never delete history"


def test_tracking_an_unknown_device_raises(three_devices) -> None:
    with session_scope() as session, pytest.raises(LookupError, match="Unknown device"):
        track_devices(session, ["NOT-A-DEVICE"])


def test_default_device_follows_the_tracked_set(three_devices) -> None:
    """The dashboard's default focus can never point at an untracked device."""
    with session_scope() as session:
        track_all(session)
        set_default_device(session, BIKE[0])
        assert get_default_device(session).device_id == BIKE[0]

        untrack_devices(session, [BIKE[0]])
        default = get_default_device(session)
        assert default is not None
        assert default.device_id != BIKE[0]
        assert default.is_tracked is True


def test_default_is_none_when_nothing_is_tracked(three_devices) -> None:
    with session_scope() as session:
        assert get_default_device(session) is None


# ---------------------------------------------------------------- polling
class MultiFakeClient:
    """Returns a different observation per device; records call order.

    Registered into the provider registry under "test-multi" (rather than
    passed to poll_once directly — E3-T4 made poll_once provider-aware and it
    no longer takes a client argument) so it stands in for a LocationProvider.
    """

    def __init__(self, per_device: dict[str, list], errors: dict | None = None) -> None:
        self.per_device = per_device
        self.errors = errors or {}
        self.calls: list[str] = []

    def locate(self, device_id: str, device_name: str):
        self.calls.append(device_id)
        if device_id in self.errors:
            raise self.errors[device_id]
        return self.per_device.get(device_id, [])

    def is_available(self) -> tuple[bool, str]:
        return (True, "")

    def is_authenticated(self) -> bool:
        return True

    def authenticate(self, interactive: bool = True) -> str:
        return "ok"

    def describe_auth(self) -> dict:
        return {}

    def list_devices(self) -> list:
        return []


def test_every_tracked_device_is_polled(three_devices, register_provider) -> None:
    with session_scope() as session:
        track_all(session)

    client = MultiFakeClient(
        {
            BIKE[0]: [make_observation(device_id=BIKE[0], device_name=BIKE[1], lat=41.10)],
            KEYS[0]: [make_observation(device_id=KEYS[0], device_name=KEYS[1], lat=42.20)],
            BAG[0]: [make_observation(device_id=BAG[0], device_name=BAG[1], lat=43.30)],
        }
    )
    register_provider("test-multi", client)
    cycle = poll_once(stagger_seconds=0)

    assert sorted(client.calls) == sorted([BIKE[0], KEYS[0], BAG[0]])
    assert cycle.inserted == 3
    assert len(cycle.outcomes) == 3


def test_untracked_devices_are_not_polled(three_devices, register_provider) -> None:
    with session_scope() as session:
        track_devices(session, [BIKE[0]], exclusive=True)

    client = MultiFakeClient({BIKE[0]: [make_observation(device_id=BIKE[0])]})
    register_provider("test-multi", client)
    poll_once(stagger_seconds=0)
    assert client.calls == [BIKE[0]]


def test_one_device_failing_does_not_stop_the_others(three_devices, register_provider) -> None:
    from findplus.findhub.types import LocationTimeoutError

    with session_scope() as session:
        track_all(session)

    client = MultiFakeClient(
        {
            BIKE[0]: [make_observation(device_id=BIKE[0], device_name=BIKE[1], lat=41.10)],
            BAG[0]: [make_observation(device_id=BAG[0], device_name=BAG[1], lat=43.30)],
        },
        errors={KEYS[0]: LocationTimeoutError("no push response")},
    )
    register_provider("test-multi", client)
    cycle = poll_once(stagger_seconds=0)

    statuses = {o.device_id: o.status for o in cycle.outcomes}
    assert statuses[KEYS[0]] == "timeout"
    assert statuses[BIKE[0]] == "ok"
    assert statuses[BAG[0]] == "ok"
    assert cycle.inserted == 2
    assert cycle.ok is True, "a partial failure is still a usable cycle"


def test_a_poll_run_is_recorded_per_device(three_devices, register_provider) -> None:
    with session_scope() as session:
        track_all(session)
    register_provider("test-multi", MultiFakeClient({}))
    poll_once(stagger_seconds=0)

    with session_scope() as session:
        runs = list(session.scalars(select(PollRun)))
        assert len(runs) == 3
        assert {r.device_id for r in runs} == {BIKE[0], KEYS[0], BAG[0]}


def test_cycle_fails_only_when_every_device_fails(three_devices, register_provider) -> None:
    from findplus.findhub.types import FindHubError

    with session_scope() as session:
        track_all(session)
    client = MultiFakeClient({}, errors={d[0]: FindHubError("down") for d in three_devices})
    register_provider("test-multi", client)
    assert poll_once(stagger_seconds=0).ok is False


def test_observations_are_attributed_to_the_right_device(three_devices, register_provider) -> None:
    with session_scope() as session:
        track_all(session)
    register_provider(
        "test-multi",
        MultiFakeClient(
            {
                BIKE[0]: [make_observation(device_id=BIKE[0], device_name=BIKE[1], lat=41.10)],
                KEYS[0]: [make_observation(device_id=KEYS[0], device_name=KEYS[1], lat=42.20)],
            }
        ),
    )
    poll_once(stagger_seconds=0)
    with session_scope() as session:
        rows = {o.device_id: o for o in session.scalars(select(LocationObservation))}
        assert round(rows[BIKE[0]].latitude, 2) == 41.10
        assert round(rows[KEYS[0]].latitude, 2) == 42.20


def test_identical_coordinates_on_two_devices_are_separate_observations(
    three_devices,
) -> None:
    """Two tags in the same bag are two facts, not a duplicate."""
    with session_scope() as session:
        result = ingest_observations(
            session,
            [
                make_observation(device_id=BIKE[0], device_name=BIKE[1], lat=41.1, minutes=0),
                make_observation(device_id=KEYS[0], device_name=KEYS[1], lat=41.1, minutes=0),
            ],
        )
        assert result.inserted == 2


# --------------------------------------------------------------- timeline
@pytest.fixture
def two_tracks(three_devices):
    """Two devices on the same day, in places far apart."""
    with session_scope() as session:
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

    everything = list(csv.DictReader(io.StringIO(two_tracks.get("/api/export?fmt=csv").text)))
    one = list(
        csv.DictReader(io.StringIO(two_tracks.get(f"/api/export?fmt=csv&device_id={BIKE[0]}").text))
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
    assert len(list(csv.DictReader(io.StringIO(inside)))) == 4
    assert len(list(csv.DictReader(io.StringIO(outside)))) == 0


def test_devices_with_data_ignores_devices_that_never_reported(two_tracks: TestClient) -> None:
    body = two_tracks.get("/api/timeline?day=2026-09-18&timezone=UTC").json()
    assert BAG[0] not in {t["device_id"] for t in body["tracks"]}
