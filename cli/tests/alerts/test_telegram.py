"""alerts/channels/telegram.py: send() and telegram_setup(), fully mocked HTTP."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from findplus.alerts.channels.telegram import DeliveryResult, send, telegram_setup

#: Shaped like a real BotFather token (digits, colon, 35-char secret) so it
#: passes store.is_valid_bot_token -- every test below that exercises the
#: real send()/_get_me()/telegram_setup() must use a token this shape now
#: that both functions reject a malformed one before making any request.
TOKEN = "9876543210:ABCdefGHIjklMNOpqrSTUvwxyz012345678"


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
        result = send("hi", TOKEN, "1")
    assert result == DeliveryResult(True, 200, None)


def test_send_retries_on_5xx() -> None:
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.post.side_effect = [_response(500), _response(200)]
        with patch("findplus.alerts.channels.telegram.time.sleep"):
            result = send("hi", TOKEN, "1")
    assert result.success is True
    assert instance.post.call_count == 2


def test_send_timeout() -> None:
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.post.side_effect = httpx.TimeoutException("timed out")
        result = send("hi", TOKEN, "1")
    assert result == DeliveryResult(False, None, "timeout")


def test_send_401_raises() -> None:
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.post.return_value = _response(401)
        with pytest.raises(ValueError, match="invalid token"):
            send("hi", TOKEN, "1")


def test_send_403_raises() -> None:
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.post.return_value = _response(403)
        with pytest.raises(ValueError, match="blocked or kicked"):
            send("hi", TOKEN, "1")


def test_setup_409_on_get_me() -> None:
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.return_value = _response(409)
        with pytest.raises(RuntimeError, match="webhook"):
            telegram_setup(TOKEN, wait_seconds=1, poll=1)


def test_setup_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    save_mock = MagicMock()
    monkeypatch.setattr("findplus.alerts.channels.telegram.save_channel", save_mock)

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
        result = telegram_setup(TOKEN, wait_seconds=120, poll=2)

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
            telegram_setup(TOKEN, wait_seconds=1, poll=1)
        assert time.monotonic() - start < 4


def test_http_error_never_echoes_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """httpx puts the request URL (which carries the token) in HTTPStatusError."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class _Failing(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), _Failing)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(
        "findplus.alerts.channels.telegram.TELEGRAM_BASE",
        f"http://127.0.0.1:{server.server_address[1]}/bot",
    )
    try:
        with pytest.raises(RuntimeError) as excinfo:
            telegram_setup(TOKEN, wait_seconds=1, poll=1)
    finally:
        server.shutdown()
        server.server_close()
    assert TOKEN not in str(excinfo.value)
    assert "500" in str(excinfo.value)


# ------------------------------------------------- group / channel setup (E12)
@pytest.mark.parametrize(
    ("key", "chat"),
    [
        ("my_chat_member", {"id": -100123, "type": "supergroup", "title": "Family"}),
        ("channel_post", {"id": -100777, "type": "channel", "title": "Alerts"}),
    ],
)
def test_setup_accepts_group_and_channel_updates(
    monkeypatch: pytest.MonkeyPatch, key: str, chat: dict
) -> None:
    """A group with privacy mode on sends only `my_chat_member`; a channel only
    sends `channel_post`. Ignoring either leaves setup hanging to the timeout."""
    monkeypatch.setattr("findplus.alerts.channels.telegram.save_channel", MagicMock())

    update = {"update_id": 1, key: {"chat": chat}}
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.get.side_effect = [
            _response(200, {"result": {"username": "testbot"}}),
            _response(200, {"result": [update]}),
        ]
        instance.post.return_value = _response(200)
        result = telegram_setup(TOKEN, wait_seconds=120, poll=2)

    assert result["chat_id"] == str(chat["id"])
    assert result["chat_title"] == chat["title"]
    assert result["chat_type"] == chat["type"]


def test_setup_tells_group_users_about_start_and_privacy_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("findplus.alerts.channels.telegram.save_channel", MagicMock())

    update = {"update_id": 1, "message": {"chat": {"id": 99, "type": "private"}}}
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.get.side_effect = [
            _response(200, {"result": {"username": "testbot"}}),
            _response(200, {"result": [update]}),
        ]
        instance.post.return_value = _response(200)
        telegram_setup(TOKEN, wait_seconds=120, poll=2)

    out = capsys.readouterr().out
    assert "/start@testbot" in out
    assert "privacy" in out.lower()
    assert "BotFather" in out


# ------------------------------------------------------ supergroup migration
def test_send_follows_migrate_to_chat_id() -> None:
    """Telegram renumbers a group when it becomes a supergroup. The old id is
    dead, so the message is re-sent to the id it hands back."""
    migrated = _response(
        400,
        {
            "ok": False,
            "description": "Bad Request: group chat was upgraded to a supergroup chat",
            "parameters": {"migrate_to_chat_id": -1001234567890},
        },
    )
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.post.side_effect = [migrated, _response(200)]
        result = send("hi", TOKEN, "-4242")

    assert result == DeliveryResult(True, 200, None)
    assert instance.post.call_count == 2
    assert instance.post.call_args_list[1].kwargs["json"]["chat_id"] == "-1001234567890"


def test_send_400_without_migration_still_raises() -> None:
    plain = _response(400, {"ok": False, "description": "Bad Request: chat not found"}, "nope")
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.post.return_value = plain
        with pytest.raises(ValueError, match="bad request"):
            send("hi", TOKEN, "1")


def test_send_does_not_loop_when_telegram_repeats_the_same_id() -> None:
    same = _response(400, {"parameters": {"migrate_to_chat_id": 1}}, "loop")
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.post.return_value = same
        with pytest.raises(ValueError, match="bad request"):
            send("hi", TOKEN, "1")


# ------------------------------------------------- malformed token (blind B2)
@pytest.mark.parametrize(
    "bad_token",
    ["tok", "", "123456", "123456:short", "not-a-token-at-all", "123456:" + "x" * 29],
)
def test_send_rejects_a_malformed_token_without_a_request(bad_token: str) -> None:
    with (
        patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client,
        pytest.raises(ValueError, match="malformed bot token"),
    ):
        send("hi", bad_token, "1")
    mock_client.assert_not_called()


def test_get_me_rejects_a_malformed_token_without_a_request() -> None:
    from findplus.alerts.channels.telegram import _get_me

    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        client = mock_client.return_value.__enter__.return_value
        with pytest.raises(ValueError, match="malformed bot token"):
            _get_me("tok", client)
    client.get.assert_not_called()


def test_setup_rejects_a_malformed_token_without_a_request() -> None:
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        client = mock_client.return_value.__enter__.return_value
        with pytest.raises(ValueError, match="malformed bot token"):
            telegram_setup("tok", wait_seconds=1, poll=1)
    client.get.assert_not_called()
