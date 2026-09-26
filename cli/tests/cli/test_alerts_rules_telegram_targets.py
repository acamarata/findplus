"""`findplus alerts rules add/edit --telegram-target/--telegram-all` (WP10,
gap-audit P13): the CLI's own path to a per-rule Telegram target subset,
mirroring the dashboard dialog's checkboxes.
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from findplus.alerts.store import AlertsChannels, TelegramCreds, save_alerts
from findplus.cli.main import main
from findplus.db.session import session_scope
from findplus.ingest import upsert_device

TOKEN = "9876543210:ABCdefGHIjklMNOpqrSTUvwxyz012345678"


def _seed_telegram(chat_ids=("1", "2", "3")) -> None:
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


def _seed_device() -> None:
    with session_scope() as s:
        upsert_device(s, "dev1", "Tag1")


def _list_json(runner: CliRunner) -> list[dict]:
    return json.loads(runner.invoke(main, ["alerts", "rules", "list", "--json"]).output)


def test_add_without_either_option_defaults_to_null_every_target(tmp_db: str) -> None:
    _seed_telegram()
    _seed_device()
    runner = CliRunner()
    result = runner.invoke(
        main, ["alerts", "rules", "add", "r1", "--device-id", "dev1", "--channel", "telegram"]
    )
    assert result.exit_code == 0, result.output
    assert _list_json(runner)[0]["telegram_targets"] is None


def test_add_with_repeated_telegram_target_stores_the_subset(tmp_db: str) -> None:
    _seed_telegram()
    _seed_device()
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "alerts",
            "rules",
            "add",
            "r1",
            "--device-id",
            "dev1",
            "--channel",
            "telegram",
            "--telegram-target",
            "1",
            "--telegram-target",
            "3",
        ],
    )
    assert result.exit_code == 0, result.output
    assert _list_json(runner)[0]["telegram_targets"] == ["1", "3"]


def test_add_rejects_a_target_that_is_not_saved(tmp_db: str) -> None:
    _seed_telegram(chat_ids=("1",))
    _seed_device()
    result = CliRunner().invoke(
        main,
        [
            "alerts",
            "rules",
            "add",
            "bad",
            "--device-id",
            "dev1",
            "--channel",
            "telegram",
            "--telegram-target",
            "999",
        ],
    )
    assert result.exit_code != 0
    assert "999" in result.output


def test_add_rejects_both_telegram_target_and_telegram_all(tmp_db: str) -> None:
    _seed_telegram()
    _seed_device()
    result = CliRunner().invoke(
        main,
        [
            "alerts",
            "rules",
            "add",
            "bad",
            "--device-id",
            "dev1",
            "--channel",
            "telegram",
            "--telegram-target",
            "1",
            "--telegram-all",
        ],
    )
    assert result.exit_code != 0
    assert "not both" in result.output


def test_edit_narrows_an_existing_rule(tmp_db: str) -> None:
    _seed_telegram()
    _seed_device()
    runner = CliRunner()
    runner.invoke(
        main, ["alerts", "rules", "add", "r1", "--device-id", "dev1", "--channel", "telegram"]
    )
    rule_id = _list_json(runner)[0]["id"]
    result = runner.invoke(
        main,
        ["alerts", "rules", "edit", str(rule_id), "--telegram-target", "2"],
    )
    assert result.exit_code == 0, result.output
    assert _list_json(runner)[0]["telegram_targets"] == ["2"]


def test_edit_telegram_all_resets_a_narrowed_rule(tmp_db: str) -> None:
    _seed_telegram()
    _seed_device()
    runner = CliRunner()
    runner.invoke(
        main,
        [
            "alerts",
            "rules",
            "add",
            "r1",
            "--device-id",
            "dev1",
            "--channel",
            "telegram",
            "--telegram-target",
            "1",
        ],
    )
    rule_id = _list_json(runner)[0]["id"]
    result = runner.invoke(main, ["alerts", "rules", "edit", str(rule_id), "--telegram-all"])
    assert result.exit_code == 0, result.output
    assert _list_json(runner)[0]["telegram_targets"] is None


def test_edit_without_telegram_options_leaves_the_subset_untouched(tmp_db: str) -> None:
    _seed_telegram()
    _seed_device()
    runner = CliRunner()
    runner.invoke(
        main,
        [
            "alerts",
            "rules",
            "add",
            "r1",
            "--device-id",
            "dev1",
            "--channel",
            "telegram",
            "--telegram-target",
            "2",
        ],
    )
    rule_id = _list_json(runner)[0]["id"]
    result = runner.invoke(main, ["alerts", "rules", "edit", str(rule_id), "--cooldown", "5"])
    assert result.exit_code == 0, result.output
    row = _list_json(runner)[0]
    assert row["telegram_targets"] == ["2"]
    assert row["cooldown_minutes"] == 5


def test_rules_list_table_shows_the_telegram_column(tmp_db: str) -> None:
    _seed_telegram()
    _seed_device()
    runner = CliRunner()
    runner.invoke(
        main,
        [
            "alerts",
            "rules",
            "add",
            "r1",
            "--device-id",
            "dev1",
            "--channel",
            "telegram",
            "--telegram-target",
            "2",
        ],
    )
    result = runner.invoke(main, ["alerts", "rules", "list"])
    assert result.exit_code == 0, result.output
    assert "TELEGRAM" in result.output
    assert "2" in result.output
