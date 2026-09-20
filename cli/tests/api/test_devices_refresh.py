"""POST /api/devices/refresh asks every signed-in provider, not just Google.

E1 honesty round 2 F4: the button says "Refresh from your providers", plural,
but the endpoint constructed FindHubClient directly, so an accessory added with
`findplus apple add-accessory` never appeared from the dashboard and nothing on
screen said Apple was CLI-only. The failure path also surfaced str(exc)
verbatim to the user.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from findplus.api import create_app
from findplus.providers.base import ProviderDevice


class _Provider:
    def __init__(self, name, devices=(), available=True, authed=True, boom=None):
        self.name = name
        self.display_name = name
        self._devices = list(devices)
        self._available = available
        self._authed = authed
        self._boom = boom

    def is_available(self):
        return self._available, ""

    def is_authenticated(self):
        return self._authed

    def list_devices(self):
        if self._boom:
            raise RuntimeError(self._boom)
        return self._devices


def _install(monkeypatch, providers: dict[str, _Provider]) -> None:
    monkeypatch.setattr(
        "findplus.providers.base.available_providers", lambda: list(providers), raising=False
    )
    monkeypatch.setattr(
        "findplus.providers.base.get_provider", lambda n: providers[n], raising=False
    )


def _device(device_id: str, provider: str = "google-find-hub") -> ProviderDevice:
    return ProviderDevice(
        provider=provider, device_id=device_id, name=device_id, kind="tracker", raw={}
    )


@pytest.fixture
def app_client(tmp_db):
    return TestClient(create_app())


def test_every_signed_in_provider_is_queried(app_client, monkeypatch) -> None:
    _install(
        monkeypatch,
        {
            "google-find-hub": _Provider("google-find-hub", [_device("G1")]),
            "apple-find-my": _Provider("apple-find-my", [_device("A1")]),
        },
    )
    body = app_client.post("/api/devices/refresh").json()

    assert body["found"] == 2
    assert sorted(body["providers"]) == ["apple-find-my", "google-find-hub"]

    rows = {d["device_id"]: d["provider"] for d in app_client.get("/api/devices").json()["devices"]}
    assert rows == {"G1": "google-find-hub", "A1": "apple-find-my"}


def test_a_provider_that_is_not_signed_in_is_skipped_not_an_error(app_client, monkeypatch) -> None:
    _install(
        monkeypatch,
        {
            "google-find-hub": _Provider("google-find-hub", [_device("G1")]),
            "apple-find-my": _Provider("apple-find-my", authed=False),
        },
    )
    body = app_client.post("/api/devices/refresh").json()

    assert body["found"] == 1
    assert body["providers"] == ["google-find-hub"]
    assert body["errors"] == {}


def test_one_providers_outage_does_not_hide_the_others_results(app_client, monkeypatch) -> None:
    _install(
        monkeypatch,
        {
            "google-find-hub": _Provider("google-find-hub", [_device("G1")]),
            "apple-find-my": _Provider("apple-find-my", boom="anisette server down"),
        },
    )
    body = app_client.post("/api/devices/refresh").json()

    assert body["found"] == 1
    assert "apple-find-my" in body["errors"]


def test_nothing_signed_in_says_so_instead_of_returning_zero(app_client, monkeypatch) -> None:
    _install(monkeypatch, {"google-find-hub": _Provider("google-find-hub", authed=False)})
    res = app_client.post("/api/devices/refresh")

    assert res.status_code == 409
    assert "findplus auth" in res.json()["detail"]


def test_a_total_failure_names_the_providers_not_the_exception(app_client, monkeypatch) -> None:
    _install(
        monkeypatch,
        {"google-find-hub": _Provider("google-find-hub", boom="TokenRefreshError at 0x7f")},
    )
    res = app_client.post("/api/devices/refresh")

    assert res.status_code == 502
    detail = res.json()["detail"]
    assert "google-find-hub" in detail
    assert "TokenRefreshError" not in detail, "a raw exception is not an actionable message"
