"""`findplus doctor [--repair] [--json]`: 10 checks + repair (P1-E7-W3-S1-T4).

Purpose : Each check function in isolation, the repair helpers, and the
          command's exit-code/JSON-shape behavior.
Constraints: Every check runs against tmp_path, never the real ~/.findplus.
"""

from __future__ import annotations

import json
import os
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
    check_sensitive_file_perms,
    check_state_dir_perms,
    check_units,
    doctor_cmd,
    repair_sensitive_file_perms,
    repair_state_dir_perms,
)


# ------------------------------------------------------------------------- a
def test_check_python_passes_on_test_runner() -> None:
    c = check_python()
    assert c.passed is True
    assert "Python" in c.detail


# ------------------------------------------------------------------------- b
def test_check_state_dir_perms(tmp_path) -> None:
    os.chmod(tmp_path, 0o700)
    assert check_state_dir_perms(tmp_path).passed is True

    os.chmod(tmp_path, 0o755)
    c = check_state_dir_perms(tmp_path)
    assert c.passed is False
    assert c.repairable is True


# ------------------------------------------------------------------------- c
def test_check_sensitive_file_perms(tmp_path) -> None:
    secrets = tmp_path / "secrets.json"
    secrets.write_text("{}")
    os.chmod(secrets, 0o644)
    c = check_sensitive_file_perms(tmp_path)
    assert c.passed is False
    assert "secrets.json" in c.detail

    os.chmod(secrets, 0o600)
    assert check_sensitive_file_perms(tmp_path).passed is True


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
def test_check_providers(tmp_path) -> None:
    from findplus.cli.doctor import check_providers

    assert check_providers(tmp_path).passed is False
    (tmp_path / "secrets.json").write_text(json.dumps({"token": "x"}))
    assert check_providers(tmp_path).passed is True


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


# ------------------------------------------------------------------------- i
def test_repair_state_dir_perms(tmp_path) -> None:
    os.chmod(tmp_path, 0o755)
    repair_state_dir_perms(tmp_path)
    assert (os.stat(tmp_path).st_mode & 0o777) == 0o700


# ------------------------------------------------------------------------- j
def test_repair_sensitive_file_perms(tmp_path) -> None:
    p = tmp_path / "secrets.json"
    p.write_text("{}")
    os.chmod(p, 0o644)
    repair_sensitive_file_perms(tmp_path)
    assert (os.stat(p).st_mode & 0o777) == 0o600


# ------------------------------------------------------------------------- k
def test_doctor_cmd_json_all_pass(monkeypatch: pytest.MonkeyPatch, tmp_db) -> None:
    ok = DoctorCheck("x", "X", True, "fine")
    monkeypatch.setattr(doctor_module, "check_python", lambda: ok)
    monkeypatch.setattr(doctor_module, "check_state_dir_perms", lambda sd: ok)
    monkeypatch.setattr(doctor_module, "check_sensitive_file_perms", lambda sd: ok)
    monkeypatch.setattr(doctor_module, "check_db_head", lambda: ok)
    monkeypatch.setattr(doctor_module, "check_providers", lambda sd: ok)
    monkeypatch.setattr(doctor_module, "check_units", lambda: ok)
    monkeypatch.setattr(doctor_module, "check_port", lambda sd, port: ok)
    monkeypatch.setattr(doctor_module, "check_chrome", lambda: ok)
    monkeypatch.setattr(doctor_module, "check_alerts_json", lambda sd: ok)
    monkeypatch.setattr(doctor_module, "check_desktop_app", lambda: ok)

    result = CliRunner().invoke(doctor_cmd, ["--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert len(data) == 10


# ------------------------------------------------------------------------- l
def test_doctor_cmd_json_one_failing_exits_1(monkeypatch: pytest.MonkeyPatch, tmp_db) -> None:
    ok = DoctorCheck("x", "X", True, "fine")
    bad = DoctorCheck("port", "Daemon port", False, "connection refused")
    monkeypatch.setattr(doctor_module, "check_python", lambda: ok)
    monkeypatch.setattr(doctor_module, "check_state_dir_perms", lambda sd: ok)
    monkeypatch.setattr(doctor_module, "check_sensitive_file_perms", lambda sd: ok)
    monkeypatch.setattr(doctor_module, "check_db_head", lambda: ok)
    monkeypatch.setattr(doctor_module, "check_providers", lambda sd: ok)
    monkeypatch.setattr(doctor_module, "check_units", lambda: ok)
    monkeypatch.setattr(doctor_module, "check_port", lambda sd, port: bad)
    monkeypatch.setattr(doctor_module, "check_chrome", lambda: ok)
    monkeypatch.setattr(doctor_module, "check_alerts_json", lambda sd: ok)
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
