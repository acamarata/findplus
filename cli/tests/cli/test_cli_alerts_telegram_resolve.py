"""`findplus alerts telegram-targets`: `@name` resolution at save time
(WP1, gap-audit P12), split out of test_cli_alerts_telegram_targets.py.

The Bot API is mocked at telegram_targets.py's own httpx.Client/list_chats,
never the network (the autouse fixture would fail it anyway).
"""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from findplus.alerts.store import AlertsChannels, TelegramCreds, save_alerts
from findplus.cli.main import main

TOKEN = "9876543210:ABCdefGHIjklMNOpqrSTUvwxyz012345678"
_MOD = "findplus.alerts.channels.telegram_targets"


def _seed_telegram(chat_ids=("1",)):
    save_alerts(
        AlertsChannels(
            telegram=TelegramCreds(
                bot_token=TOKEN,
                chat_ids=chat_ids,
                chat_title="t",
                bot_username="b",
                captured_at="now",
            )
        )
    )


def test_telegram_targets_resolves_a_public_group_via_get_chat(tmp_db: str) -> None:
    _seed_telegram()
    with patch(f"{_MOD}.httpx.Client") as mock_client:
        mock_client.return_value.get.return_value.status_code = 200
        mock_client.return_value.get.return_value.json.return_value = {
            "result": {"id": -100555, "type": "supergroup", "title": "Family"}
        }
        result = CliRunner().invoke(main, ["alerts", "telegram-targets", "@family_group"])
    assert result.exit_code == 0, result.output
    assert "-100555" in result.output

    from findplus.alerts.store import load_alerts

    assert load_alerts().telegram.chat_ids == ("-100555",)
    assert load_alerts().telegram.chat_labels == ("Family",)


def test_telegram_targets_resolves_a_person_via_get_updates(tmp_db: str) -> None:
    _seed_telegram()
    with (
        patch(f"{_MOD}.httpx.Client") as mock_client,
        patch(f"{_MOD}.list_chats") as mock_list_chats,
    ):
        mock_client.return_value.get.return_value.status_code = 400
        mock_list_chats.return_value = [{"id": "555", "type": "private", "username": "alice"}]
        result = CliRunner().invoke(main, ["alerts", "telegram-targets", "@alice"])
    assert result.exit_code == 0, result.output

    from findplus.alerts.store import load_alerts

    assert load_alerts().telegram.chat_ids == ("555",)
    assert load_alerts().telegram.chat_labels == ("@alice",)


def test_telegram_targets_unresolved_name_is_a_click_exception(tmp_db: str) -> None:
    _seed_telegram()
    with (
        patch(f"{_MOD}.httpx.Client") as mock_client,
        patch(f"{_MOD}.list_chats", return_value=[]),
    ):
        mock_client.return_value.get.return_value.status_code = 400
        result = CliRunner().invoke(main, ["alerts", "telegram-targets", "@nobody_yet"])
    assert result.exit_code != 0
    assert "@nobody_yet hasn't messaged your bot yet" in result.output
    assert "save again" in result.output


def test_telegram_targets_mixed_list_resolves_every_entry(tmp_db: str) -> None:
    _seed_telegram()
    with (
        patch(f"{_MOD}.httpx.Client") as mock_client,
        patch(f"{_MOD}.list_chats") as mock_list_chats,
    ):
        mock_client.return_value.get.return_value.status_code = 400
        mock_list_chats.return_value = [{"id": "9", "type": "private", "username": "alice"}]
        result = CliRunner().invoke(
            main, ["alerts", "telegram-targets", "--", "-100123, @alice, 555"]
        )
    assert result.exit_code == 0, result.output

    from findplus.alerts.store import load_alerts

    assert load_alerts().telegram.chat_ids == ("-100123", "9", "555")
