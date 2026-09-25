"""`findplus alerts telegram-targets` and the multi-target `alerts test
--channel telegram` CLI parity for the comma-separated targets feature.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from findplus.alerts.store import AlertsChannels, TelegramCreds, save_alerts
from findplus.cli.main import main

TOKEN = "9876543210:ABCdefGHIjklMNOpqrSTUvwxyz012345678"


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


def test_telegram_targets_not_configured(tmp_db: str) -> None:
    result = CliRunner().invoke(main, ["alerts", "telegram-targets", "111"])
    assert result.exit_code != 0
    assert "not configured" in result.output


def test_telegram_targets_sets_the_list(tmp_db: str) -> None:
    _seed_telegram()
    result = CliRunner().invoke(main, ["alerts", "telegram-targets", "111, -100222, @person"])
    assert result.exit_code == 0, result.output
    assert "111" in result.output
    assert "-100222" in result.output
    assert "@person" in result.output

    from findplus.alerts.store import load_alerts

    assert load_alerts().telegram.chat_ids == ("111", "-100222", "@person")


def test_telegram_targets_bad_entry_names_the_value(tmp_db: str) -> None:
    _seed_telegram()
    result = CliRunner().invoke(main, ["alerts", "telegram-targets", "111,not-a-target"])
    assert result.exit_code != 0
    assert "not-a-target" in result.output


def test_telegram_targets_keeps_the_token_untouched(tmp_db: str) -> None:
    _seed_telegram()
    CliRunner().invoke(main, ["alerts", "telegram-targets", "222"])
    from findplus.alerts.store import load_alerts

    assert load_alerts().telegram.bot_token == TOKEN


def test_test_telegram_reports_per_target_and_fails_if_any_target_failed(
    tmp_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_telegram(chat_ids=("good", "bad"))

    def _send(text, bot_token, chat_id, **kw):
        if chat_id == "bad":
            return MagicMock(success=False, error="blocked")
        return MagicMock(success=True, error=None)

    monkeypatch.setattr("findplus.cli.alerts_channels.send", _send)
    result = CliRunner().invoke(main, ["alerts", "test", "--channel", "telegram"])
    assert result.exit_code != 0
    assert "good: sent" in result.output
    assert "bad: failed" in result.output


def test_test_telegram_all_targets_ok_exits_zero(
    tmp_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_telegram(chat_ids=("a", "b"))
    monkeypatch.setattr(
        "findplus.cli.alerts_channels.send",
        lambda *a, **kw: MagicMock(success=True, error=None),
    )
    result = CliRunner().invoke(main, ["alerts", "test", "--channel", "telegram"])
    assert result.exit_code == 0, result.output
    assert "a: sent" in result.output
    assert "b: sent" in result.output


def test_test_telegram_no_targets_is_an_error(tmp_db: str) -> None:
    _seed_telegram(chat_ids=())
    result = CliRunner().invoke(main, ["alerts", "test", "--channel", "telegram"])
    assert result.exit_code != 0
    assert "not configured" in result.output
