"""alerts/channels/telegram.py: send() and telegram_setup(), fully mocked HTTP."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from findplus.alerts.channels.telegram import DeliveryResult, send, telegram_setup


def _response(status_code: int, json_body: dict | None = None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = json_body or {}
    resp.raise_for_status = MagicMock()
    return resp


def test_send_happy_path() -> None:
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.post.return_value = _response(200)
        result = send("hi", "tok", "1")
    assert result == DeliveryResult(True, 200, None)


def test_send_retries_on_5xx() -> None:
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.post.side_effect = [_response(500), _response(200)]
        with patch("findplus.alerts.channels.telegram.time.sleep"):
            result = send("hi", "tok", "1")
    assert result.success is True
    assert instance.post.call_count == 2


def test_send_timeout() -> None:
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.post.side_effect = httpx.TimeoutException("timed out")
        result = send("hi", "tok", "1")
    assert result == DeliveryResult(False, None, "timeout")


def test_send_401_raises() -> None:
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.post.return_value = _response(401)
        with pytest.raises(ValueError, match="invalid token"):
            send("hi", "tok", "1")


def test_send_403_raises() -> None:
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.post.return_value = _response(403)
        with pytest.raises(ValueError, match="blocked or kicked"):
            send("hi", "tok", "1")


def test_setup_409_on_get_me() -> None:
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.return_value = _response(409)
        with pytest.raises(RuntimeError, match="webhook"):
            telegram_setup("tok", wait_seconds=1, poll=1)


def test_setup_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    save_mock = MagicMock()
    monkeypatch.setattr("findplus.alerts.channels.telegram.save_alerts", save_mock)

    update = {
        "update_id": 1,
        "message": {"chat": {"id": 99, "type": "private", "username": "user1"}},
    }
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.get.side_effect = [
            _response(200, {"result": {"username": "testbot"}}),  # getMe
            _response(200, {"result": [update]}),  # getUpdates
        ]
        instance.post.return_value = _response(200)  # sendMessage confirmation
        result = telegram_setup("tok", wait_seconds=120, poll=2)

    assert result["chat_id"] == "99"
    assert result["bot_username"] == "testbot"
    save_mock.assert_called_once()


def test_setup_timeout() -> None:
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.get.side_effect = [
            _response(200, {"result": {"username": "testbot"}}),  # getMe
        ] + [_response(200, {"result": []})] * 50  # empty getUpdates, repeated
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            telegram_setup("tok", wait_seconds=1, poll=1)
        assert time.monotonic() - start < 4
