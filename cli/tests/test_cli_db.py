"""`findplus db upgrade|current|path`."""

from __future__ import annotations

from click.testing import CliRunner

from findplus.cli.cmd_db import db_cmd


def test_db_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("FINDPLUS_STATE_DIR", raising=False)
    result = CliRunner().invoke(db_cmd, ["path"])
    assert result.exit_code == 0
    assert "findplus.sqlite" in result.output


def test_db_upgrade_creates_tables(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("FINDPLUS_STATE_DIR", raising=False)
    CliRunner().invoke(db_cmd, ["upgrade"], catch_exceptions=False)

    from sqlalchemy import create_engine, inspect

    db = tmp_path / ".findplus" / "findplus.sqlite"
    assert db.exists()
    assert "devices" in inspect(create_engine(f"sqlite:///{db}")).get_table_names()


def test_db_current_after_upgrade(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("FINDPLUS_STATE_DIR", raising=False)
    runner = CliRunner()
    runner.invoke(db_cmd, ["upgrade"], catch_exceptions=False)
    result = runner.invoke(db_cmd, ["current"])
    assert result.exit_code == 0
    assert "(base" not in result.output
