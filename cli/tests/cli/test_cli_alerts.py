"""`findplus alerts` — guard, url validation, unconfigured cases, rules."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from findplus.alerts.store import AlertsChannels
from findplus.cli.main import main


def test_telegram_clear_no_yes(tmp_db: str) -> None:
    result = CliRunner().invoke(main, ["alerts", "telegram-clear"])
    assert result.exit_code != 0


def test_webhook_set_invalid_url(tmp_db: str) -> None:
    result = CliRunner().invoke(main, ["alerts", "webhook-set", "ftp://bad"])
    assert result.exit_code != 0


def test_webhook_set_https_ok(tmp_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("findplus.cli.alerts.save_alerts", MagicMock())
    result = CliRunner().invoke(main, ["alerts", "webhook-set", "https://example.com/hook"])
    assert result.exit_code == 0


def test_test_channel_not_configured(tmp_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("findplus.cli.alerts.load_alerts", lambda: AlertsChannels())
    result = CliRunner().invoke(main, ["alerts", "test", "--channel", "telegram"])
    assert result.exit_code != 0
    assert "not configured" in result.output


def test_rules_list_empty(tmp_db: str) -> None:
    result = CliRunner().invoke(main, ["alerts", "rules", "list"])
    assert result.exit_code == 0


def test_rules_add_requires_exactly_one_target(tmp_db: str) -> None:
    result = CliRunner().invoke(main, ["alerts", "rules", "add", "r1", "--channel", "telegram"])
    assert result.exit_code != 0


def test_rules_add_and_remove(tmp_db: str) -> None:
    from findplus.db.session import session_scope
    from findplus.ingest import upsert_device

    with session_scope() as s:
        upsert_device(s, "dev1", "Tag1")

    runner = CliRunner()
    add_result = runner.invoke(
        main, ["alerts", "rules", "add", "r1", "--device-id", "dev1", "--channel", "telegram"]
    )
    assert add_result.exit_code == 0
    rule_id = add_result.output.split("Created rule ", 1)[1].split(":", 1)[0]

    list_result = runner.invoke(main, ["alerts", "rules", "list"])
    assert "r1" in list_result.output

    remove_result = runner.invoke(main, ["alerts", "rules", "remove", rule_id, "--yes"])
    assert remove_result.exit_code == 0
    assert "Removed." in remove_result.output


def test_deliveries_empty(tmp_db: str) -> None:
    result = CliRunner().invoke(main, ["alerts", "deliveries"])
    assert result.exit_code == 0


def test_alerts_help_lists_subcommands(tmp_db: str) -> None:
    result = CliRunner().invoke(main, ["alerts", "--help"])
    assert result.exit_code == 0
    for name in ("telegram-setup", "webhook-set", "test", "rules", "deliveries"):
        assert name in result.output
