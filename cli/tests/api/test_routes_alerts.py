"""/api/alerts/channels/*: telegram/webhook CRUD, the test-send endpoint, and
the app lock. Rules CRUD and the deliveries log moved to
test_routes_alerts_rules.py (E13 stage 2, size cap).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from findplus.alerts.store import AlertsChannels, TelegramCreds, save_alerts
from findplus.db.session import session_scope
from findplus.ingest import upsert_device

#: Shaped like a real BotFather token, so a mocked _get_me/telegram_setup is reached (blind B2).
TOKEN = "9876543210:ABCdefGHIjklMNOpqrSTUvwxyz012345678"


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
                chat_ids=("1",),
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
        "findplus.api.routes_alerts_telegram._get_me",
        MagicMock(side_effect=ValueError("telegram: invalid token (401)")),
    )
    res = client.put("/api/alerts/channels/telegram", json={"bot_token": TOKEN})
    assert res.status_code == 400


def test_setup_timeout(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "findplus.api.routes_alerts_telegram.telegram_setup",
        MagicMock(side_effect=TimeoutError("no message received within 1 s")),
    )
    res = client.post("/api/alerts/channels/telegram/setup?wait=1", json={"bot_token": TOKEN})
    assert res.status_code == 408


def test_setup_webhook_conflict(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "findplus.api.routes_alerts_telegram.telegram_setup",
        MagicMock(side_effect=RuntimeError("telegram: webhook conflict (409)")),
    )
    res = client.post("/api/alerts/channels/telegram/setup?wait=1", json={"bot_token": TOKEN})
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
                bot_token="tok",
                chat_ids=("1",),
                chat_title="t",
                bot_username="b",
                captured_at="now",
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
                bot_token="tok",
                chat_ids=("1",),
                chat_title="t",
                bot_username="b",
                captured_at="now",
            )
        )
    )
    with patch("findplus.api.routes_alerts_telegram.send") as send_mock:
        send_mock.return_value = MagicMock(success=True, error=None)
        res = client.post("/api/alerts/test", json={"channel": "telegram"})
    assert res.status_code == 200
    assert res.json()["status"] == "sent"


def test_test_endpoint_reports_failure_instead_of_500(client: TestClient) -> None:
    save_alerts(
        AlertsChannels(
            telegram=TelegramCreds(
                bot_token="tok",
                chat_ids=("1",),
                chat_title="t",
                bot_username="b",
                captured_at="now",
            )
        )
    )
    with patch(
        "findplus.api.routes_alerts_telegram.send",
        side_effect=ValueError("telegram: invalid token (401)"),
    ):
        res = client.post("/api/alerts/test", json={"channel": "telegram"})
    assert res.status_code == 200
    assert res.json()["status"] == "failed"


def test_401_locked(client: TestClient) -> None:
    client.post("/api/settings/pin", json={"new_pin": "864213"})
    client.cookies.clear()
    res = client.get("/api/alerts/channels")
    assert res.status_code == 401


def test_put_webhook_rejects_lookalike_loopback_host(client: TestClient) -> None:
    res = client.put(
        "/api/alerts/channels/webhook",
        json={"url": "http://localhost.evil.example/hook", "secret": None},
    )
    assert res.status_code == 422
