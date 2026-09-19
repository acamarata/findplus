"""/api/alerts/*: channels, rules CRUD, deliveries, and the app lock."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from findplus.alerts.store import AlertsChannels, TelegramCreds, save_alerts
from findplus.db.session import session_scope
from findplus.ingest import upsert_device


@pytest.fixture
def client(tmp_db):
    from findplus.api import create_app

    with session_scope() as session:
        upsert_device(session, "dev1", "Tag1")
    return TestClient(create_app())


def test_get_channels_unconfigured(client: TestClient) -> None:
    body = client.get("/api/alerts/channels").json()
    assert body["telegram"]["configured"] is False
    assert body["webhook"]["configured"] is False


def test_get_channels_masked(client: TestClient) -> None:
    save_alerts(
        AlertsChannels(
            telegram=TelegramCreds(
                bot_token="1234567890:ABCxyzabcxyz1234",
                chat_id="1",
                chat_title="t",
                bot_username="b",
                captured_at="now",
            )
        )
    )
    res = client.get("/api/alerts/channels")
    body = res.json()
    masked = body["telegram"]["bot_token_masked"]
    assert masked.startswith("1234")
    assert masked.endswith("1234")
    assert "1234567890:ABCxyzabcxyz1234" not in res.text


def test_put_telegram_invalid_token(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "findplus.api.routes_alerts_channels._get_me",
        MagicMock(side_effect=ValueError("telegram: invalid token (401)")),
    )
    res = client.put("/api/alerts/channels/telegram", json={"bot_token": "bad"})
    assert res.status_code == 400


def test_setup_timeout(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "findplus.api.routes_alerts_channels.telegram_setup",
        MagicMock(side_effect=TimeoutError("no message received within 1 s")),
    )
    res = client.post("/api/alerts/channels/telegram/setup?wait=1", json={"bot_token": "tok"})
    assert res.status_code == 408


def test_setup_webhook_conflict(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "findplus.api.routes_alerts_channels.telegram_setup",
        MagicMock(side_effect=RuntimeError("telegram: webhook conflict (409)")),
    )
    res = client.post("/api/alerts/channels/telegram/setup?wait=1", json={"bot_token": "tok"})
    assert res.status_code == 409


def test_put_webhook_bad_url(client: TestClient) -> None:
    res = client.put("/api/alerts/channels/webhook", json={"url": "ftp://bad", "secret": None})
    assert res.status_code == 422


def test_put_webhook_https_ok(client: TestClient) -> None:
    res = client.put(
        "/api/alerts/channels/webhook", json={"url": "https://example.com/hook", "secret": None}
    )
    assert res.status_code == 200
    assert res.json()["webhook"]["configured"] is True


def test_delete_telegram(client: TestClient) -> None:
    save_alerts(
        AlertsChannels(
            telegram=TelegramCreds(
                bot_token="tok", chat_id="1", chat_title="t", bot_username="b", captured_at="now"
            )
        )
    )
    res = client.delete("/api/alerts/channels/telegram")
    assert res.status_code == 204
    assert client.get("/api/alerts/channels").json()["telegram"]["configured"] is False


def test_test_endpoint_not_configured(client: TestClient) -> None:
    res = client.post("/api/alerts/test", json={"channel": "telegram"})
    assert res.status_code == 422


def test_test_endpoint_sends(client: TestClient) -> None:
    save_alerts(
        AlertsChannels(
            telegram=TelegramCreds(
                bot_token="tok", chat_id="1", chat_title="t", bot_username="b", captured_at="now"
            )
        )
    )
    with patch("findplus.api.routes_alerts_channels.send") as send_mock:
        send_mock.return_value = MagicMock(success=True, error=None)
        res = client.post("/api/alerts/test", json={"channel": "telegram"})
    assert res.status_code == 200
    assert res.json()["status"] == "sent"


def test_rules_crud(client: TestClient) -> None:
    create = client.post(
        "/api/alerts/rules",
        json={"name": "r1", "device_id": "dev1", "channel": "telegram"},
    )
    assert create.status_code == 201
    body = create.json()
    assert body["device_id"] == "dev1"
    rule_id = body["id"]

    listed = client.get("/api/alerts/rules").json()
    assert any(r["id"] == rule_id for r in listed)

    updated = client.put(f"/api/alerts/rules/{rule_id}", json={"enabled": False})
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False

    deleted = client.delete(f"/api/alerts/rules/{rule_id}")
    assert deleted.status_code == 204

    assert client.get("/api/alerts/rules").json() == []


def test_rules_create_requires_exactly_one_target(client: TestClient) -> None:
    res = client.post("/api/alerts/rules", json={"name": "bad", "channel": "telegram"})
    assert res.status_code == 422


def test_deliveries_empty(client: TestClient) -> None:
    assert client.get("/api/alerts/deliveries").json() == []


def test_401_locked(client: TestClient) -> None:
    client.post("/api/settings/pin", json={"new_pin": "8642"})
    client.cookies.clear()
    res = client.get("/api/alerts/channels")
    assert res.status_code == 401
