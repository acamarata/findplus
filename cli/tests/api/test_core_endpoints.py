"""GET /api/version, /api/widget, and the E8 additions to /api/status and /api/config."""

from __future__ import annotations

import importlib.metadata

from fastapi.testclient import TestClient

from findplus import honesty
from tests.test_api import client, locked_client  # noqa: F401


def test_version(client: TestClient) -> None:  # noqa: F811
    body = client.get("/api/version").json()
    assert set(body) >= {"version", "python", "platform", "providers", "apple_extra_installed"}
    assert body["version"] == importlib.metadata.version("findplus")


def test_widget_unlocked(client: TestClient) -> None:  # noqa: F811
    body = client.get("/api/widget").json()
    for key in (
        "state",
        "version",
        "last_poll_at",
        "next_poll_at",
        "tracked_count",
        "devices",
        "groups",
        "show_map",
        "notice",
    ):
        assert key in body, key
    assert body["notice"] == "Locations can be minutes to hours late."
    assert body["state"] in {"ok", "stale", "error"}


def test_widget_locked(locked_client: TestClient) -> None:  # noqa: F811
    assert locked_client.get("/api/widget").status_code == 401


def test_status_new_fields(client: TestClient) -> None:  # noqa: F811
    body = client.get("/api/status").json()
    assert isinstance(body["provider_health"], list)
    assert isinstance(body["alerts_configured"], bool)
    assert isinstance(body["consecutive_failures"], int)
    assert body["last_error_type"] is None or isinstance(body["last_error_type"], str)


def test_config_notices(client: TestClient) -> None:  # noqa: F811
    notices = client.get("/api/config").json()["notices"]
    expected_keys = {
        "find_hub",
        "apple",
        "alerts_latency",
        "presence_stale",
        "lock_not_encryption",
        "not_affiliated",
    }
    assert set(notices) == expected_keys
    for value in notices.values():
        assert isinstance(value, str) and value
    assert notices["find_hub"] == honesty.FIND_HUB
