"""GET /api/version, /api/widget, and the E8 additions to /api/status and /api/config."""

from __future__ import annotations

import importlib.metadata
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from findplus import honesty
from findplus.api._helpers import _widget_state
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


@pytest.mark.parametrize(
    "error_type,failures,age_minutes,expected",
    [
        (None, 0, 1, "ok"),
        (None, 2, 1, "ok"),
        ("network", 0, 1, "ok"),
        ("auth", 0, 1, "error"),
        ("decrypt", 0, 1, "error"),
        (None, 3, 1, "error"),
        (None, 0, 11, "stale"),
        (None, 0, 9, "ok"),  # just inside 2 x the 5-minute interval
        # Both conditions true at once: api-contract.md orders error first.
        ("auth", 4, 60, "error"),
        (None, 4, 60, "error"),
        (None, None, None, "ok"),
    ],
)
def test_widget_state_priority(error_type, failures, age_minutes, expected) -> None:
    """`_widget_state` returns only ok|stale|error, error winning over stale."""
    last_poll_at = (
        None if age_minutes is None else datetime.now(UTC) - timedelta(minutes=age_minutes)
    )
    state = _widget_state(error_type, failures or 0, last_poll_at, 5 * 60)
    assert state == expected


def test_widget_state_never_returns_down() -> None:
    """`down` is rendered by the widget client on a connection failure (widget.md)."""
    for error_type in (None, "auth", "decrypt", "network", "down"):
        for failures in (0, 3, 99):
            assert _widget_state(error_type, failures, None, 300) in {"ok", "stale", "error"}
