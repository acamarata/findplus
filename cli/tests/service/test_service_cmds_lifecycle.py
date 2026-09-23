"""D15 stop/restart/status/uninstall commands (P1-E7-W3-S1-T1).

Purpose : The thin facade-dispatch commands split out of test_service_cmds.py
          (T1, 2026-09-22, PRI rule-7 300-line file cap) -- `start`'s own
          state machine stays there. Facade dispatch and the plan snapshots
          live in test_service_plans.py, `auth` in test_auth_cmd.py.
Constraints: Tests never touch the real ~/.findplus or the network.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from findplus.cli.main import main
from tests.service._helpers import patch_manager as _patch_manager


# ------------------------------------------------------------------------ stop
def test_stop_calls_facade_and_explains_next_steps(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []
    monkeypatch.setattr("findplus.service.is_installed", lambda *a, **k: True)
    monkeypatch.setattr("findplus.service.stop", lambda *a, **k: calls.append(True))
    result = CliRunner().invoke(main, ["stop"])
    assert result.exit_code == 0, result.output
    assert calls == [True]
    assert "uninstall --yes" in result.output
    assert "next login" in result.output


def test_stop_without_a_service_says_nothing_was_stopped(
    tmp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[bool] = []
    monkeypatch.setattr("findplus.service.is_installed", lambda *a, **k: False)
    monkeypatch.setattr("findplus.service.stop", lambda *a, **k: calls.append(True))
    result = CliRunner().invoke(main, ["stop"])
    assert result.exit_code == 0, result.output
    assert calls == []
    assert "nothing was stopped" in result.output
    assert "Stopped." not in result.output


# --------------------------------------------------------------------- restart
def test_restart_calls_facade_restart_service(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_manager(monkeypatch, "launchd")
    calls: list[bool] = []
    monkeypatch.setattr("findplus.service.restart_service", lambda: calls.append(True) or True)
    result = CliRunner().invoke(main, ["restart"])
    assert result.exit_code == 0, result.output
    assert calls == [True]


# ---------------------------------------------------------------------- status
def test_status_json_with_daemon_down_parses(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a, **k):
        raise ConnectionError("refused")

    monkeypatch.setattr("httpx.get", _raise)
    result = CliRunner().invoke(main, ["status", "--json"])
    assert result.exit_code == 0, result.output
    out = json.loads(result.output)
    assert out["version"] is None
    assert out["lock_state"] == "unknown"


def test_status_falls_back_to_daemon_json_for_version(
    tmp_db, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Build-notes carry-forward #16: `port` fell back to daemon.json and
    `version` did not, so an unreachable daemon printed `version None` even
    with a daemon.json on disk recording the version it was started with."""

    def _raise(*a, **k):
        raise ConnectionError("refused")

    monkeypatch.setattr("httpx.get", _raise)
    from findplus.config import get_settings

    daemon_file = get_settings().daemon_file
    daemon_file.parent.mkdir(parents=True, exist_ok=True)
    daemon_file.write_text(
        json.dumps({"pid": 1, "port": 9999, "host": "127.0.0.1", "version": "1.0.0.dev0"})
    )
    try:
        result = CliRunner().invoke(main, ["status", "--json"])
        assert result.exit_code == 0, result.output
        out = json.loads(result.output)
        assert out["version"] == "1.0.0.dev0"
        assert out["port"] == 9999
    finally:
        daemon_file.unlink(missing_ok=True)


def test_status_text_has_service_and_watchdog_lines(
    tmp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(*a, **k):
        raise ConnectionError("refused")

    monkeypatch.setattr("httpx.get", _raise)
    result = CliRunner().invoke(main, ["status"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert any(line.startswith("service") for line in lines)
    assert any(line.startswith("watchdog") for line in lines)


# ------------------------------------------------------------------- uninstall
def test_uninstall_without_yes_does_not_call_facade(
    tmp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[bool] = []
    monkeypatch.setattr("findplus.service.uninstall", lambda *a, **k: calls.append(True))
    result = CliRunner().invoke(main, ["uninstall"])
    assert result.exit_code == 0, result.output
    assert "--yes" in result.output
    assert calls == []


def test_uninstall_yes_calls_both_facades(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("findplus.service.uninstall", lambda *a, **k: calls.append("uninstall"))
    monkeypatch.setattr(
        "findplus.service.uninstall_watchdog", lambda *a, **k: calls.append("watchdog")
    )
    result = CliRunner().invoke(main, ["uninstall", "--yes"])
    assert result.exit_code == 0, result.output
    assert calls == ["uninstall", "watchdog"]
