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
