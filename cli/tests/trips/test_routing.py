"""The opt-in road route: off by default, own-server only, degrades to dashed lines."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from findplus import honesty
from findplus.api import create_app
from findplus.trips.routing import MAX_POINTS, likely_route, normalize_endpoint
from tests.trips._db import DEVICE, seed_school_day
from tests.trips._fake_osrm import FakeOsrm
from tests.trips._synth import HOME, Day, offset


def _points(n: int = 3):
    day = Day()
    for i in range(n):
        day.at(i * 5, offset(HOME, 300 * i, 300 * i), acc=40.0)
    return day.fixes


def test_no_request_without_an_endpoint() -> None:
    with FakeOsrm() as osrm:
        for empty in (None, "", "   "):
            out = likely_route(empty, _points())
            assert out["style"] == "dashed" and out["source"] == "straight"
        assert osrm.requests == []


def test_routed_answer_carries_the_label() -> None:
    with FakeOsrm() as osrm:
        out = likely_route(osrm.url, _points())
    assert out["style"] == "solid" and out["source"] == "match"
    assert out["label"] == honesty.ROUTE_LIKELY
    assert out["geometry"]["type"] == "LineString" and len(out["geometry"]["coordinates"]) == 3
    assert osrm.requests[0].startswith("/match/v1/driving/")


def test_falls_back_from_match_to_route() -> None:
    with FakeOsrm(match="nomatch") as osrm:
        out = likely_route(osrm.url, _points())
    assert out["source"] == "route" and out["label"] == honesty.ROUTE_LIKELY
    assert [r.split("/")[1] for r in osrm.requests] == ["match", "route"]


@pytest.mark.parametrize("mode", ["500", "junk", "nomatch"])
def test_failures_degrade_to_straight_dashed_segments(mode: str) -> None:
    pts = _points()
    with FakeOsrm(match=mode, route=mode) as osrm:
        out = likely_route(osrm.url, pts)
    assert out["style"] == "dashed" and out["source"] == "straight"
    assert out["label"] == honesty.TRIPS_APPROXIMATE
    assert out["geometry"]["coordinates"] == [[p.lon, p.lat] for p in pts]


def test_unreachable_server_degrades_quietly() -> None:
    out = likely_route("http://127.0.0.1:9", _points())  # nothing listens on the discard port
    assert out["style"] == "dashed"


def test_long_trips_are_sampled_and_keep_both_ends() -> None:
    with FakeOsrm() as osrm:
        likely_route(osrm.url, _points(500))
    coords = osrm.requests[0].split("/driving/")[1].split("?")[0].split(";")
    assert len(coords) == MAX_POINTS


@pytest.mark.parametrize(
    "bad", ["ftp://x", "localhost:5000", "http://user:pw@h", "http://h/?a=1", "http://"]
)
def test_endpoint_validation(bad: str) -> None:
    with pytest.raises(ValueError):
        normalize_endpoint(bad)
    assert normalize_endpoint("http://127.0.0.1:5000/") == "http://127.0.0.1:5000"


@pytest.fixture
def client(tmp_db) -> TestClient:
    seed_school_day()
    return TestClient(create_app())


def _first_trip_id(client: TestClient) -> str:
    body = client.get(
        "/api/trips", params={"device_id": DEVICE, "date": "2026-09-18", "timezone": "UTC"}
    ).json()
    return body["trips"][0]["id"]


def _route(client: TestClient, trip_id: str, **extra):
    params = {"device_id": DEVICE, "trip_id": trip_id, "timezone": "UTC", **extra}
    return client.get("/api/trips/route", params=params)


def test_route_endpoint_is_off_by_default_and_sends_nothing(client: TestClient) -> None:
    with FakeOsrm() as osrm:
        trip_id = _first_trip_id(client)
        body = _route(client, trip_id).json()
        assert osrm.requests == []
    assert body["style"] == "dashed" and body["routing_notice"] == honesty.ROUTING_PRIVACY
    assert client.get("/api/settings/routing.endpoint").json() == {"routing.endpoint": ""}
    assert (
        client.get("/api/trips", params={"device_id": DEVICE, "date": "2026-09-18"}).json()[
            "routing_enabled"
        ]
        is False
    )


def test_route_endpoint_uses_only_the_configured_server(client: TestClient) -> None:
    trip_id = _first_trip_id(client)
    with FakeOsrm() as osrm:
        resp = client.post("/api/settings/routing.endpoint", json={"value": osrm.url + "/"})
        assert resp.status_code == 200 and resp.json()["notice"] == honesty.ROUTING_PRIVACY
        body = _route(client, trip_id, date="2026-09-18", days=1).json()
        assert body["source"] == "match" and body["label"] == honesty.ROUTE_LIKELY
        assert len(osrm.requests) == 1
        # Clearing the setting turns it off again.
        client.post("/api/settings/routing.endpoint", json={"value": ""})
        assert _route(client, trip_id).json()["style"] == "dashed"
        assert len(osrm.requests) == 1


def test_bad_endpoint_is_rejected_and_unknown_trip_404(client: TestClient) -> None:
    assert (
        client.post("/api/settings/routing.endpoint", json={"value": "ftp://x"}).status_code == 422
    )
    assert _route(client, "t1").status_code == 404
    assert _route(client, "banana").status_code == 422
