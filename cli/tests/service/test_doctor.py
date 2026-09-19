"""`findplus doctor [--repair] [--json]`: individual checks + the command's
exit-code/JSON-shape behavior (P1-E7-W3-S1-T4).

Purpose : Each non-perms, non-legacy-database check function in isolation,
          plus the doctor_cmd CLI behavior. State-dir/sensitive-file
          permission checks split to test_doctor_repairs.py; legacy-database
          detection split to test_doctor_legacy.py (PRI rule 7, <=300
          lines/file).
Constraints: Every check runs against tmp_path, never the real ~/.findplus.
"""

from __future__ import annotations

import json
import sys

import pytest
from click.testing import CliRunner

from findplus.cli import doctor as doctor_module
from findplus.cli.doctor import (
    DoctorCheck,
    check_alerts_json,
    check_chrome,
    check_db_head,
    check_desktop_app,
    check_python,
    check_units,
    doctor_cmd,
)


# ------------------------------------------------------------------------- a
def test_check_python_passes_on_test_runner() -> None:
    c = check_python()
    assert c.passed is True
    assert "Python" in c.detail


# ------------------------------------------------------------------------- d
def test_check_db_head(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("findplus.db.migrate.current_revision", lambda: "0002")
    monkeypatch.setattr("findplus.db.migrate.head_revision", lambda: "0002")
    assert check_db_head().passed is True

    monkeypatch.setattr("findplus.db.migrate.head_revision", lambda: "0003")
    c = check_db_head()
    assert c.passed is False
    assert c.repairable is True

    def _raise():
        raise RuntimeError("no db file")

    monkeypatch.setattr("findplus.db.migrate.current_revision", _raise)
    c = check_db_head()
    assert c.passed is False
    assert "no db file" in c.detail


# ------------------------------------------------------------------------- e
def test_check_providers_not_signed_in(tmp_db) -> None:
    """No secrets.json anywhere: every registered provider is not signed-in.

    CF23: rewritten to go through the provider registry; the rest of this
    check's coverage (account reporting, the Apple honesty line) lives in
    test_doctor_providers.py to keep this file under the line cap."""
    from findplus.cli.doctor import check_providers

    c = check_providers()
    assert c.passed is False


# ------------------------------------------------------------------------- f
def test_check_port(monkeypatch: pytest.MonkeyPatch) -> None:
    from findplus.cli.doctor import check_port

    class _Resp:
        def __init__(self, code: int) -> None:
            self.status_code = code

    monkeypatch.setattr("httpx.get", lambda *a, **k: _Resp(200))
    assert check_port(None, 8647).passed is True

    monkeypatch.setattr("httpx.get", lambda *a, **k: _Resp(401))
    assert check_port(None, 8647).passed is True

    def _raise(*a, **k):
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr("httpx.get", _raise)
    c = check_port(None, 8647)
    assert c.passed is False
    assert c.repairable is False


# ------------------------------------------------------------------------- g
def test_check_alerts_json(tmp_path) -> None:
    assert check_alerts_json(tmp_path).passed is True  # not present

    (tmp_path / "alerts.json").write_text("{}")
    assert check_alerts_json(tmp_path).passed is True  # valid

    (tmp_path / "alerts.json").write_text("{not json")
    c = check_alerts_json(tmp_path)
    assert c.passed is False
    assert c.detail


# ------------------------------------------------------------------------- h
def test_check_units(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Plan:
        unit_path = "/home/x/unit"

    monkeypatch.setattr("findplus.service.is_installed", lambda: True)
    monkeypatch.setattr("findplus.service.plan", lambda: _Plan())
    c = check_units()
    assert c.passed is True
    assert "/home/x/unit" in c.detail

    monkeypatch.setattr("findplus.service.is_installed", lambda: False)
    c = check_units()
    assert c.passed is False
    assert "not installed" in c.detail


# ------------------------------------------------------------------------- k
def test_doctor_cmd_json_all_pass(monkeypatch: pytest.MonkeyPatch, tmp_db) -> None:
    ok = DoctorCheck("x", "X", True, "fine")
    monkeypatch.setattr(doctor_module, "check_python", lambda: ok)
    monkeypatch.setattr(doctor_module, "check_state_dir_perms", lambda sd: ok)
    monkeypatch.setattr(doctor_module, "check_sensitive_file_perms", lambda sd: ok)
    monkeypatch.setattr(doctor_module, "check_db_head", lambda: ok)
    monkeypatch.setattr(doctor_module, "check_providers", lambda: ok)
    monkeypatch.setattr(doctor_module, "check_units", lambda: ok)
    monkeypatch.setattr(doctor_module, "check_port", lambda sd, port: ok)
    monkeypatch.setattr(doctor_module, "check_chrome", lambda: ok)
    monkeypatch.setattr(doctor_module, "check_alerts_json", lambda sd: ok)
    monkeypatch.setattr(doctor_module, "check_legacy_database", lambda db: ok)
    monkeypatch.setattr(doctor_module, "check_desktop_app", lambda: ok)

    result = CliRunner().invoke(doctor_cmd, ["--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert len(data) == 11


# ------------------------------------------------------------------------- l
def test_doctor_cmd_json_one_failing_exits_1(monkeypatch: pytest.MonkeyPatch, tmp_db) -> None:
    ok = DoctorCheck("x", "X", True, "fine")
    bad = DoctorCheck("port", "Daemon port", False, "connection refused")
    monkeypatch.setattr(doctor_module, "check_python", lambda: ok)
    monkeypatch.setattr(doctor_module, "check_state_dir_perms", lambda sd: ok)
    monkeypatch.setattr(doctor_module, "check_sensitive_file_perms", lambda sd: ok)
    monkeypatch.setattr(doctor_module, "check_db_head", lambda: ok)
    monkeypatch.setattr(doctor_module, "check_providers", lambda: ok)
    monkeypatch.setattr(doctor_module, "check_units", lambda: ok)
    monkeypatch.setattr(doctor_module, "check_port", lambda sd, port: bad)
    monkeypatch.setattr(doctor_module, "check_chrome", lambda: ok)
    monkeypatch.setattr(doctor_module, "check_alerts_json", lambda sd: ok)
    monkeypatch.setattr(doctor_module, "check_legacy_database", lambda db: ok)
    monkeypatch.setattr(doctor_module, "check_desktop_app", lambda: ok)

    result = CliRunner().invoke(doctor_cmd, ["--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert any(not row["passed"] for row in data)


# ------------------------------------------------------------------------- m
def test_check_desktop_app_non_darwin_always_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    c = check_desktop_app()
    assert c.passed is True


def test_check_chrome_runs_without_raising() -> None:
    c = check_chrome()
    assert isinstance(c.passed, bool)
