"""GET /api/places/search: throttling, timeout, error mapping, lock, host guard.

Purpose : Nominatim is reached through `routes_places_search._fetch_from_
          nominatim`, the one seam this file replaces -- the autouse
          network-block fixture (cli/tests/conftest.py) forbids a real
          socket regardless, so an un-mocked call would fail as a
          connection error rather than exercise the real behaviour.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from findplus.api import routes_places_search as search_mod


@pytest.fixture
def client(tmp_db):
    from findplus.api import create_app

    return TestClient(create_app())


@pytest.fixture(autouse=True)
def _reset_throttle():
    """Every test starts as though no prior request has ever gone out."""
    search_mod._last_request_monotonic = None
    yield
    search_mod._last_request_monotonic = None


def _ok_response(rows) -> httpx.Response:
    request = httpx.Request("GET", search_mod.NOMINATIM_URL)
    return httpx.Response(200, json=rows, request=request)


ONE_ROW = [{"display_name": "1 Main St, Springfield", "lat": "41.1", "lon": "-80.64"}]


def test_blank_query_is_422_before_any_outbound_call(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = []
    monkeypatch.setattr(search_mod, "_fetch_from_nominatim", lambda q: called.append(q))
    res = client.get("/api/places/search", params={"q": "   "})
    assert res.status_code == 422
    assert called == []


def test_a_result_row_is_shaped_and_capped_at_five(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [{"display_name": f"Place {i}", "lat": str(i), "lon": str(-i)} for i in range(1, 8)]
    monkeypatch.setattr(search_mod, "_fetch_from_nominatim", lambda q: _ok_response(rows))
    res = client.get("/api/places/search", params={"q": "Home"})
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 5
    assert body[0] == {"display_name": "Place 1", "latitude": 1.0, "longitude": -1.0}


def test_a_malformed_row_is_skipped_not_fatal(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [{"display_name": "Good", "lat": "1", "lon": "2"}, {"display_name": "Bad, no coords"}]
    monkeypatch.setattr(search_mod, "_fetch_from_nominatim", lambda q: _ok_response(rows))
    res = client.get("/api/places/search", params={"q": "Home"})
    assert res.status_code == 200
    assert res.json() == [{"display_name": "Good", "latitude": 1.0, "longitude": 2.0}]


def test_timeout_maps_to_504(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_timeout(q):
        raise httpx.TimeoutException("slow")

    monkeypatch.setattr(search_mod, "_fetch_from_nominatim", raise_timeout)
    res = client.get("/api/places/search", params={"q": "Home"})
    assert res.status_code == 504


def test_connection_failure_maps_to_502(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_connect_error(q):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(search_mod, "_fetch_from_nominatim", raise_connect_error)
    res = client.get("/api/places/search", params={"q": "Home"})
    assert res.status_code == 502


def test_a_non_200_upstream_status_maps_to_502(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = httpx.Request("GET", search_mod.NOMINATIM_URL)
    monkeypatch.setattr(
        search_mod, "_fetch_from_nominatim", lambda q: httpx.Response(503, request=request)
    )
    res = client.get("/api/places/search", params={"q": "Home"})
    assert res.status_code == 502


def test_malformed_json_maps_to_502(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("GET", search_mod.NOMINATIM_URL)
    monkeypatch.setattr(
        search_mod,
        "_fetch_from_nominatim",
        lambda q: httpx.Response(200, content=b"not json", request=request),
    )
    res = client.get("/api/places/search", params={"q": "Home"})
    assert res.status_code == 502


def test_a_non_list_json_body_maps_to_502(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = httpx.Request("GET", search_mod.NOMINATIM_URL)
    monkeypatch.setattr(
        search_mod,
        "_fetch_from_nominatim",
        lambda q: httpx.Response(200, json={"error": "nope"}, request=request),
    )
    res = client.get("/api/places/search", params={"q": "Home"})
    assert res.status_code == 502


def test_user_agent_is_descriptive_and_carries_the_repo_url(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = {}

    def fake_fetch(q):
        captured["query"] = q
        return _ok_response(ONE_ROW)

    monkeypatch.setattr(search_mod, "_fetch_from_nominatim", fake_fetch)
    client.get("/api/places/search", params={"q": "Main St"})
    assert captured["query"] == "Main St"
    assert "FindPlus" in search_mod._USER_AGENT
    assert "github.com/acamarata/findplus" in search_mod._USER_AGENT


def test_throttle_waits_out_the_remainder_of_one_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unit-level: the throttle gate itself, not the route, so the test does
    not need to actually sleep a full second."""
    times = iter([100.0, 100.2, 100.2])  # first call, second call's "now" x2
    monkeypatch.setattr(search_mod.time, "monotonic", lambda: next(times))
    slept = []
    monkeypatch.setattr(search_mod.time, "sleep", lambda s: slept.append(s))

    search_mod._wait_for_throttle_slot()  # first call: nothing to wait for
    search_mod._wait_for_throttle_slot()  # second call: 0.2s later, needs 0.8s more

    assert slept == [pytest.approx(0.8)]


def test_throttle_does_not_wait_once_a_full_second_has_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    times = iter([100.0, 101.5])
    monkeypatch.setattr(search_mod.time, "monotonic", lambda: next(times))
    slept = []
    monkeypatch.setattr(search_mod.time, "sleep", lambda s: slept.append(s))

    search_mod._wait_for_throttle_slot()
    search_mod._wait_for_throttle_slot()

    assert slept == []


def test_locked(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(search_mod, "_fetch_from_nominatim", lambda q: _ok_response(ONE_ROW))
    client.post("/api/settings/pin", json={"new_pin": "864213"})
    client.cookies.clear()
    res = client.get("/api/places/search", params={"q": "Home"})
    assert res.status_code == 401
    assert res.json()["locked"] is True


def test_a_rebound_hostname_cannot_reach_the_search_route(client: TestClient) -> None:
    res = client.get(
        "/api/places/search", params={"q": "Home"}, headers={"Host": "evil.example.com"}
    )
    assert res.status_code == 421
