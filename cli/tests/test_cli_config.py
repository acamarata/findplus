"""`findplus config get|set|unset|list|path`."""

from __future__ import annotations

from click.testing import CliRunner

from findplus.cli.cmd_config import config_cmd


def test_set_and_get(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("FINDPLUS_STATE_DIR", raising=False)
    runner = CliRunner()
    result = runner.invoke(config_cmd, ["set", "LOG_LEVEL", "DEBUG"])
    assert result.exit_code == 0
    result = runner.invoke(config_cmd, ["get", "LOG_LEVEL"])
    assert "DEBUG" in result.output


def test_reject_non_loopback_host(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("FINDPLUS_STATE_DIR", raising=False)
    runner = CliRunner()
    result = runner.invoke(config_cmd, ["set", "HOST", "0.0.0.0"])
    assert result.exit_code != 0
    assert "Non-loopback" in result.output


def test_unset(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("FINDPLUS_STATE_DIR", raising=False)
    runner = CliRunner()
    runner.invoke(config_cmd, ["set", "KEY", "VAL"])
    runner.invoke(config_cmd, ["unset", "KEY"])
    result = runner.invoke(config_cmd, ["get", "KEY"])
    assert result.output.strip() == ""


def test_config_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("FINDPLUS_STATE_DIR", raising=False)
    runner = CliRunner()
    result = runner.invoke(config_cmd, ["path"])
    assert result.output.strip().endswith("config.env")


def test_set_value_reaches_settings(tmp_path, monkeypatch) -> None:
    """A value written by `config set` must actually be read back by Settings.

    specs/data-model.md § state dir: config.env keys are field names upper-cased,
    the FINDPLUS_ prefix optional. Both forms must load.
    """
    from findplus.config import get_settings

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("FINDPLUS_STATE_DIR", raising=False)
    monkeypatch.delenv("FINDPLUS_LOG_LEVEL", raising=False)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    assert runner.invoke(config_cmd, ["set", "LOG_LEVEL", "DEBUG"]).exit_code == 0
    assert get_settings().log_level == "DEBUG"

    assert runner.invoke(config_cmd, ["set", "FINDPLUS_UI_REFRESH_SECONDS", "90"]).exit_code == 0
    assert get_settings().ui_refresh_seconds == 90


def test_env_var_beats_config_env(tmp_path, monkeypatch) -> None:
    from findplus.config import get_settings

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("FINDPLUS_STATE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert CliRunner().invoke(config_cmd, ["set", "LOG_LEVEL", "DEBUG"]).exit_code == 0
    monkeypatch.setenv("FINDPLUS_LOG_LEVEL", "WARNING")
    assert get_settings().log_level == "WARNING"
