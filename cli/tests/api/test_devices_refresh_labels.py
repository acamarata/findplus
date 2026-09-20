"""POST /api/devices/refresh keeps a user's label, icon and colour (D-P2-4).

Purpose : The same guarantee `test_ingest_labels.py` proves at the function
          level, proven through the real HTTP route a dashboard button calls.
Constraints: No network. The route asks every registered provider, so the fake
          provider is installed the way cli/tests/api/test_devices_refresh.py
          already does it (the route stopped constructing FindHubClient itself
          in E1 honesty round 2 F4).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from findplus.api import create_app
from findplus.db.session import session_scope
from findplus.ingest import upsert_device
from findplus.providers.base import ProviderDevice


class _Provider:
    """The smallest thing `_query_every_provider` will accept as signed in."""

    def __init__(self, name: str, devices: list[ProviderDevice]) -> None:
        self.name = name
        self.display_name = name
        self._devices = devices

    def is_available(self) -> tuple[bool, str]:
        return True, ""

    def is_authenticated(self) -> bool:
        return True

    def list_devices(self) -> list[ProviderDevice]:
        return self._devices


@pytest.fixture
def client(tmp_db):
    with session_scope() as session:
        upsert_device(session, "dev1", "Tag1")
    return TestClient(create_app())


def test_refresh_route_preserves_a_user_set_label(client: TestClient, monkeypatch) -> None:
    patched = client.patch(
        "/api/devices/dev1",
        json={"label": "Mom", "icon": "lucide:user-round", "color": "#37c67a"},
    )
    assert patched.status_code == 200, patched.text

    provider = _Provider(
        "google-find-hub",
        [
            ProviderDevice(
                provider="google-find-hub",
                device_id="dev1",
                name="Tag1 From Google",
                kind="tracker",
                raw={},
            )
        ],
    )
    monkeypatch.setattr(
        "findplus.providers.base.available_providers", lambda: ["google-find-hub"], raising=False
    )
    monkeypatch.setattr(
        "findplus.providers.base.get_provider", lambda _name: provider, raising=False
    )

    assert client.post("/api/devices/refresh").status_code == 200

    row = client.get("/api/devices").json()["devices"][0]
    assert row["name"] == "Tag1 From Google"
    assert row["label"] == "Mom"
    assert row["icon"] == "lucide:user-round"
    assert row["color"] == "#37c67a"
