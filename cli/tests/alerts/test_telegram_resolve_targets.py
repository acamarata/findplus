"""alerts/channels/telegram_targets.py: resolve_targets(), the save-time
`@name` -> numeric id lookup (WP1, gap-audit P12).

Every Telegram Bot API call is mocked at the module's own `httpx.Client` and
`list_chats` -- no test here touches the network (the autouse fixture in
conftest.py would fail it anyway).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from findplus.alerts.channels.telegram_targets import ResolvedTarget, resolve_targets

from ._telegram_helpers import TOKEN, _response

_MOD = "findplus.alerts.channels.telegram_targets"


def test_resolve_single_numeric_id_makes_no_request() -> None:
    with patch(f"{_MOD}.httpx.Client") as mock_client:
        result = resolve_targets("123456789", TOKEN)
    assert result == (ResolvedTarget("123456789", "123456789"),)
    mock_client.assert_not_called()


def test_resolve_negative_group_id_makes_no_request() -> None:
    with patch(f"{_MOD}.httpx.Client") as mock_client:
        result = resolve_targets("-1001234567890", TOKEN)
    assert result == (ResolvedTarget("-1001234567890", "-1001234567890"),)
    mock_client.assert_not_called()


def test_resolve_public_group_via_get_chat() -> None:
    with patch(f"{_MOD}.httpx.Client") as mock_client:
        instance = mock_client.return_value
        instance.get.return_value = _response(
            200, {"result": {"id": -100555, "type": "supergroup", "title": "Family"}}
        )
        result = resolve_targets("@family_group", TOKEN)
    assert result == (ResolvedTarget("-100555", "Family"),)


def test_resolve_public_channel_prefers_username_label() -> None:
    with patch(f"{_MOD}.httpx.Client") as mock_client:
        instance = mock_client.return_value
        instance.get.return_value = _response(
            200,
            {"result": {"id": -100777, "type": "channel", "title": "Alerts", "username": "alerts"}},
        )
        result = resolve_targets("@alerts", TOKEN)
    assert result == (ResolvedTarget("-100777", "@alerts"),)


def test_resolve_person_falls_back_to_get_updates() -> None:
    """getChat can't find a private person; getUpdates has seen them."""
    with (
        patch(f"{_MOD}.httpx.Client") as mock_client,
        patch(f"{_MOD}.list_chats") as mock_list_chats,
    ):
        mock_client.return_value.get.return_value = _response(
            400, {"ok": False, "description": "Bad Request: chat not found"}
        )
        mock_list_chats.return_value = [
            {"id": "555", "type": "private", "title": "Alice", "username": "Alice_1"}
        ]
        result = resolve_targets("@alice_1", TOKEN)
    assert result == (ResolvedTarget("555", "@Alice_1"),)
    mock_list_chats.assert_called_once_with(TOKEN)


def test_resolve_unresolved_name_names_the_target() -> None:
    with (
        patch(f"{_MOD}.httpx.Client") as mock_client,
        patch(f"{_MOD}.list_chats", return_value=[]),
    ):
        mock_client.return_value.get.return_value = _response(400)
        with pytest.raises(ValueError, match=r"@bobby hasn't messaged your bot yet") as excinfo:
            resolve_targets("@bobby", TOKEN)
    assert "save again" in str(excinfo.value)


def test_resolve_mixed_list_person_group_and_numeric() -> None:
    """The owner's own example: "-100123, @alice, 555"."""
    with (
        patch(f"{_MOD}.httpx.Client") as mock_client,
        patch(f"{_MOD}.list_chats") as mock_list_chats,
    ):
        mock_client.return_value.get.return_value = _response(400)
        mock_list_chats.return_value = [{"id": "9", "type": "private", "username": "alice"}]
        result = resolve_targets("-100123, @alice, 555", TOKEN)
    assert result == (
        ResolvedTarget("-100123", "-100123"),
        ResolvedTarget("9", "@alice"),
        ResolvedTarget("555", "555"),
    )


def test_resolve_dedupes_when_two_entries_resolve_to_the_same_id() -> None:
    with patch(f"{_MOD}.httpx.Client") as mock_client:
        instance = mock_client.return_value
        instance.get.return_value = _response(200, {"result": {"id": 555, "type": "private"}})
        result = resolve_targets("555, @same_person", TOKEN)
    assert result == (ResolvedTarget("555", "555"),)


def test_resolve_rejects_a_malformed_token_without_a_request() -> None:
    with (
        patch(f"{_MOD}.httpx.Client") as mock_client,
        pytest.raises(ValueError, match="malformed bot token"),
    ):
        resolve_targets("123", "tok")
    mock_client.assert_not_called()


def test_resolve_get_chat_401_raises_without_leaking_the_token() -> None:
    with patch(f"{_MOD}.httpx.Client") as mock_client:
        mock_client.return_value.get.return_value = _response(401)
        with pytest.raises(ValueError, match="invalid token") as excinfo:
            resolve_targets("@someone", TOKEN)
    assert TOKEN not in str(excinfo.value)


def test_resolve_get_chat_409_webhook_conflict_raises() -> None:
    with patch(f"{_MOD}.httpx.Client") as mock_client:
        mock_client.return_value.get.return_value = _response(409)
        with pytest.raises(RuntimeError, match="webhook"):
            resolve_targets("@someone", TOKEN)


def test_resolve_propagates_bad_shape_from_parse_targets() -> None:
    with (
        patch(f"{_MOD}.httpx.Client") as mock_client,
        pytest.raises(ValueError, match="invalid Telegram target"),
    ):
        resolve_targets("not-a-target", TOKEN)
    mock_client.assert_not_called()
