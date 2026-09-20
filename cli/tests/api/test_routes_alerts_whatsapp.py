"""/api/alerts/channels/whatsapp and POST /api/alerts/test {"channel":"whatsapp"}.

Purpose : Pin the E.164 422, the masked GET shape, the clear round-trip and, above
          all, that neither the raw phone nor the apikey ever appears in any
          response body.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from findplus.alerts.channels.telegram import DeliveryResult
from findplus.alerts.store import AlertsChannels, WebhookCreds, save_alerts

PHONE = "+34123123123"
APIKEY = "1234567890"


@pytest.fixture
def client(tmp_db):
    from findplus.api import create_app

    return TestClient(create_app())


def _configure(client: TestClient) -> None:
    res = client.put("/api/alerts/channels/whatsapp", json={"phone": PHONE, "apikey": APIKEY})
    assert res.status_code == 200, res.text


def test_put_rejects_a_non_e164_phone_before_writing_anything(client: TestClient) -> None:
    for bad in ("34123123123", "+0123456789", "+341", "not a phone"):
        res = client.put("/api/alerts/channels/whatsapp", json={"phone": bad, "apikey": APIKEY})
        assert res.status_code == 422, bad
    assert client.get("/api/alerts/channels").json()["whatsapp"]["configured"] is False


def test_put_then_get_returns_a_masked_phone_and_never_the_apikey(client: TestClient) -> None:
    _configure(client)
    res = client.get("/api/alerts/channels")
    body = res.json()["whatsapp"]
    assert body["configured"] is True
    assert body["phone_masked"] == "+34…23"
    assert body["phone_masked"] != PHONE
    assert APIKEY not in res.text
    assert PHONE not in res.text
    assert "apikey" not in res.text


def test_the_put_response_itself_leaks_neither_value(client: TestClient) -> None:
    res = client.put("/api/alerts/channels/whatsapp", json={"phone": PHONE, "apikey": APIKEY})
    assert APIKEY not in res.text
    assert PHONE not in res.text


def test_delete_clears_whatsapp_and_leaves_the_other_channels_alone(client: TestClient) -> None:
    save_alerts(AlertsChannels(webhook=WebhookCreds(url="https://example.com/hook", secret=None)))
    _configure(client)
    res = client.delete("/api/alerts/channels/whatsapp")
    assert res.status_code == 204
    body = client.get("/api/alerts/channels").json()
    assert body["whatsapp"]["configured"] is False
    assert body["whatsapp"]["phone_masked"] is None
    assert body["webhook"]["configured"] is True


def test_put_whatsapp_does_not_clear_telegram_or_webhook(client: TestClient) -> None:
    save_alerts(AlertsChannels(webhook=WebhookCreds(url="https://example.com/hook", secret="s")))
    _configure(client)
    body = client.get("/api/alerts/channels").json()
    assert body["webhook"]["configured"] is True
    assert body["whatsapp"]["configured"] is True


def test_test_send_uses_the_stored_credentials(client: TestClient) -> None:
    _configure(client)
    sender = MagicMock(return_value=DeliveryResult(True, 200, None))
    with patch("findplus.alerts.channels.whatsapp_callmebot.send", sender):
        res = client.post("/api/alerts/test", json={"channel": "whatsapp"})
    assert res.status_code == 200
    assert res.json() == {"status": "sent", "error": None}
    assert sender.call_args[0][1:] == (PHONE, APIKEY)


def test_test_send_reports_a_failure_without_raising(client: TestClient) -> None:
    _configure(client)
    failed = DeliveryResult(False, 200, "Error: apikey is invalid <redacted>")
    with patch("findplus.alerts.channels.whatsapp_callmebot.send", MagicMock(return_value=failed)):
        res = client.post("/api/alerts/test", json={"channel": "whatsapp"})
    assert res.json()["status"] == "failed"
    assert APIKEY not in res.text


def test_test_send_422s_when_whatsapp_is_not_configured(client: TestClient) -> None:
    res = client.post("/api/alerts/test", json={"channel": "whatsapp"})
    assert res.status_code == 422


def test_test_send_422s_for_native_which_has_no_outbound_send(client: TestClient) -> None:
    res = client.post("/api/alerts/test", json={"channel": "native"})
    assert res.status_code == 422


def test_the_whatsapp_routes_are_gated_by_the_app_lock(client: TestClient) -> None:
    client.post("/api/settings/pin", json={"new_pin": "864213"})
    client.cookies.clear()
    assert (
        client.put(
            "/api/alerts/channels/whatsapp", json={"phone": PHONE, "apikey": "k"}
        ).status_code
        == 401
    )
    assert client.delete("/api/alerts/channels/whatsapp").status_code == 401
