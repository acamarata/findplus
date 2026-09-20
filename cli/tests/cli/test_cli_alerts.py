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
    monkeypatch.setattr("findplus.cli.alerts.save_channel", MagicMock())
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


def test_webhook_set_rejects_lookalike_loopback_host(tmp_db: str) -> None:
    result = CliRunner().invoke(main, ["alerts", "webhook-set", "http://localhost.evil.example/h"])
    assert result.exit_code != 0


def test_whatsapp_is_a_subgroup_with_set_and_clear(tmp_db: str) -> None:
    """F13: `alerts whatsapp set|clear`, never top-level whatsapp-set/whatsapp-clear."""
    result = CliRunner().invoke(main, ["alerts", "whatsapp", "--help"])
    assert result.exit_code == 0
    assert "set" in result.output
    assert "clear" in result.output


def test_whatsapp_set_rejects_a_non_e164_phone(tmp_db: str) -> None:
    result = CliRunner().invoke(
        main, ["alerts", "whatsapp", "set", "--phone", "34123", "--apikey", "k"]
    )
    assert result.exit_code != 0
    assert "E.164" in result.output


def test_whatsapp_set_then_clear_round_trips(tmp_db: str) -> None:
    from findplus.alerts.store import load_alerts

    runner = CliRunner()
    set_result = runner.invoke(
        main,
        ["alerts", "whatsapp", "set", "--phone", "+34123123123", "--apikey", "1234567890"],
    )
    assert set_result.exit_code == 0, set_result.output
    assert "+34…23" in set_result.output
    assert "1234567890" not in set_result.output
    assert "+34123123123" not in set_result.output
    assert load_alerts().whatsapp.apikey == "1234567890"

    assert runner.invoke(main, ["alerts", "whatsapp", "clear"]).exit_code != 0  # needs --yes
    clear_result = runner.invoke(main, ["alerts", "whatsapp", "clear", "--yes"])
    assert clear_result.exit_code == 0
    assert load_alerts().whatsapp is None


def test_test_channel_whatsapp_not_configured(tmp_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("findplus.cli.alerts.load_alerts", lambda: AlertsChannels())
    result = CliRunner().invoke(main, ["alerts", "test", "--channel", "whatsapp"])
    assert result.exit_code != 0
    assert "WhatsApp not configured" in result.output


def test_rules_add_takes_a_repeatable_channel_option(tmp_db: str) -> None:
    from findplus.db.models_alerts import AlertRule
    from findplus.db.session import session_scope
    from findplus.ingest import upsert_device

    with session_scope() as s:
        upsert_device(s, "dev1", "Tag1")

    result = CliRunner().invoke(
        main,
        [
            "alerts",
            "rules",
            "add",
            "multi",
            "--device-id",
            "dev1",
            "--channel",
            "telegram",
            "--channel",
            "native",
        ],
    )
    assert result.exit_code == 0, result.output
    with session_scope() as s:
        assert s.query(AlertRule).one().channels == "native,telegram"


def test_rules_add_rejects_an_unknown_channel(tmp_db: str) -> None:
    result = CliRunner().invoke(
        main,
        ["alerts", "rules", "add", "bad", "--device-id", "dev1", "--channel", "sms"],
    )
    assert result.exit_code != 0


def test_rules_list_json_carries_the_channels_column(tmp_db: str) -> None:
    import json as json_mod

    from findplus.db.session import session_scope
    from findplus.ingest import upsert_device

    with session_scope() as s:
        upsert_device(s, "dev1", "Tag1")
    runner = CliRunner()
    runner.invoke(
        main,
        ["alerts", "rules", "add", "r", "--device-id", "dev1", "--channel", "whatsapp"],
    )
    listed = json_mod.loads(runner.invoke(main, ["alerts", "rules", "list", "--json"]).output)
    assert listed[0]["channels"] == "whatsapp"
    assert "channel" not in listed[0]
