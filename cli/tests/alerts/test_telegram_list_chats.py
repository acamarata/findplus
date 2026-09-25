"""alerts/channels/telegram.py: list_chats(), the "Find chat IDs" helper.

Split out of test_telegram.py (PRI rule 7's 300-line cap, pushed over by
multi-target Telegram support) -- send()/telegram_setup() stayed behind;
this file owns only the getUpdates-based chat-discovery helper.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from findplus.alerts.channels.telegram import list_chats

from ._telegram_helpers import TOKEN, _response


def test_list_chats_rejects_a_malformed_token_without_a_request() -> None:
    with (
        patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client,
        pytest.raises(ValueError, match="malformed bot token"),
    ):
        list_chats("tok")
    mock_client.assert_not_called()


def test_list_chats_returns_empty_when_no_updates_pending() -> None:
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.return_value = _response(
            200, {"result": []}
        )
        assert list_chats(TOKEN) == []


def test_list_chats_never_advances_the_offset() -> None:
    """Never passes `offset` -- Telegram would otherwise mark those updates
    read, and telegram_setup()'s own long-poll could then miss them."""
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.get.return_value = _response(200, {"result": []})
        list_chats(TOKEN)
    params = instance.get.call_args.kwargs["params"]
    assert "offset" not in params


def test_list_chats_returns_distinct_chats_private_group_and_channel() -> None:
    updates = {
        "result": [
            {
                "update_id": 1,
                "message": {
                    "chat": {
                        "id": 111,
                        "type": "private",
                        "username": "alice",
                        "first_name": "Alice",
                    }
                },
            },
            {
                "update_id": 2,
                "my_chat_member": {
                    "chat": {"id": -100222, "type": "supergroup", "title": "Family"}
                },
            },
            {
                "update_id": 3,
                "channel_post": {"chat": {"id": -100333, "type": "channel", "title": "Alerts"}},
            },
        ]
    }
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.return_value = _response(200, updates)
        chats = list_chats(TOKEN)
    by_id = {c["id"]: c for c in chats}
    assert set(by_id) == {"111", "-100222", "-100333"}
    assert by_id["111"]["type"] == "private"
    assert by_id["111"]["username"] == "alice"
    assert by_id["-100222"]["title"] == "Family"
    assert by_id["-100333"]["title"] == "Alerts"


def test_list_chats_dedupes_the_same_chat_seen_twice() -> None:
    updates = {
        "result": [
            {"update_id": 1, "message": {"chat": {"id": 111, "type": "private"}}},
            {"update_id": 2, "message": {"chat": {"id": 111, "type": "private"}}},
        ]
    }
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.return_value = _response(200, updates)
        chats = list_chats(TOKEN)
    assert len(chats) == 1


def test_list_chats_401_raises_without_leaking_the_token() -> None:
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.return_value = _response(401)
        with pytest.raises(ValueError, match="invalid token") as excinfo:
            list_chats(TOKEN)
    assert TOKEN not in str(excinfo.value)


def test_list_chats_409_webhook_conflict() -> None:
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.return_value = _response(409)
        with pytest.raises(RuntimeError, match="webhook"):
            list_chats(TOKEN)


def test_list_chats_never_returns_the_token() -> None:
    updates = {"result": [{"update_id": 1, "message": {"chat": {"id": 111, "type": "private"}}}]}
    with patch("findplus.alerts.channels.telegram.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.return_value = _response(200, updates)
        chats = list_chats(TOKEN)
    assert TOKEN not in repr(chats)
