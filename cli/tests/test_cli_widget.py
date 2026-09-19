"""`findplus widget show-map on|off` and `findplus widget refresh`."""

from __future__ import annotations

from unittest.mock import MagicMock

from click.testing import CliRunner

from findplus.cli.main import main
from findplus.state import get_setting


def test_show_map_on_writes_setting(tmp_db: str) -> None:
    result = CliRunner().invoke(main, ["widget", "show-map", "on"])
    assert result.exit_code == 0

    from findplus.db.session import session_scope

    with session_scope() as session:
        assert get_setting(session, "widget.show_map") == "1"


def test_show_map_off_writes_setting(tmp_db: str) -> None:
    runner = CliRunner()
    runner.invoke(main, ["widget", "show-map", "on"])
    result = runner.invoke(main, ["widget", "show-map", "off"])
    assert result.exit_code == 0

    from findplus.db.session import session_scope

    with session_scope() as session:
        assert get_setting(session, "widget.show_map") == "0"


def test_widget_help_lists_subcommands(tmp_db: str) -> None:
    result = CliRunner().invoke(main, ["widget", "--help"])
    assert result.exit_code == 0
    assert "show-map" in result.output
    assert "refresh" in result.output


def test_show_map_help_mentions_apple_maps(tmp_db: str) -> None:
    result = CliRunner().invoke(main, ["widget", "show-map", "--help"])
    assert result.exit_code == 0
    assert "Apple Maps" in result.output


def test_show_map_bogus_value_is_usage_error(tmp_db: str) -> None:
    result = CliRunner().invoke(main, ["widget", "show-map", "bogus"])
    assert result.exit_code == 2


def test_refresh_app_not_installed(tmp_db: str, monkeypatch) -> None:
    failing = MagicMock(returncode=1)
    monkeypatch.setattr("findplus.cli.widget.subprocess.run", lambda *a, **k: failing)
    result = CliRunner().invoke(main, ["widget", "refresh"])
    assert result.exit_code == 1
    assert "app not installed" in result.output


def test_refresh_succeeds_when_app_installed(tmp_db: str, monkeypatch) -> None:
    succeeding = MagicMock(returncode=0)
    monkeypatch.setattr("findplus.cli.widget.subprocess.run", lambda *a, **k: succeeding)
    result = CliRunner().invoke(main, ["widget", "refresh"])
    assert result.exit_code == 0
