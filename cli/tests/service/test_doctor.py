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
    check_legacy_database,
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


# ------------------------------------------------------------------------ c2
def test_apple_key_store_is_covered(tmp_path) -> None:
    """PRI hard rule 9 / E11 review carry-forward #26: `apple/` is 0700 and each
    `apple/<device_id>.json` (a plist or a raw private key) is 0600."""
    apple = tmp_path / "apple"
    apple.mkdir(mode=0o700)
    key_file = apple / "apple-abc123.json"
    key_file.write_text("{}")
    os.chmod(key_file, 0o644)

    c = check_sensitive_file_perms(tmp_path)
    assert c.passed is False
    assert "apple-abc123.json" in c.detail

    repair_sensitive_file_perms(tmp_path)
    assert check_sensitive_file_perms(tmp_path).passed is True
    assert os.stat(key_file).st_mode & 0o777 == 0o600


def test_apple_directory_mode_is_checked_and_repaired(tmp_path) -> None:
    apple = tmp_path / "apple"
    apple.mkdir()
    os.chmod(apple, 0o755)

    c = check_sensitive_file_perms(tmp_path)
    assert c.passed is False
    assert "0o700" in c.detail

    repair_sensitive_file_perms(tmp_path)
    assert os.stat(apple).st_mode & 0o777 == 0o700
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


# ------------------------------------------------------------------------- n
def test_check_legacy_database_passes_when_nothing_is_there(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(doctor_module, "legacy_database_paths", lambda: [tmp_path / "gone.sqlite"])
    c = check_legacy_database(tmp_path / "current.sqlite")
    assert c.passed is True
    assert c.detail == "none found"


def test_check_legacy_database_reports_a_pre_rename_file(tmp_path, monkeypatch) -> None:
    """A user upgrading from bike-tracker must be told their history is there,
    and told how to keep it — Find+ never migrates it silently."""
    old = tmp_path / "data" / "bike-tracker.sqlite"
    old.parent.mkdir()
    old.write_bytes(b"SQLite format 3\x00")
    current = tmp_path / "state" / "findplus.sqlite"
    monkeypatch.setattr(doctor_module, "legacy_database_paths", lambda: [old])

    c = check_legacy_database(current)

    assert c.passed is False
    assert c.repairable is False
    assert str(old) in c.detail
    assert "FINDPLUS_DATABASE_PATH" in c.detail
    assert "Nothing is moved for you." in c.detail


def test_check_legacy_database_ignores_the_database_in_use(tmp_path, monkeypatch) -> None:
    """The old default path is a legitimate current path when it is the one
    FINDPLUS_DATABASE_PATH points at; that must not be reported as a find."""
    db = tmp_path / "data" / "findplus.sqlite"
    db.parent.mkdir()
    db.write_bytes(b"SQLite format 3\x00")
    monkeypatch.setattr(doctor_module, "legacy_database_paths", lambda: [db])

    assert check_legacy_database(db).passed is True


def test_legacy_database_paths_cover_both_old_names(monkeypatch) -> None:
    names = {p.name for p in doctor_module.legacy_database_paths()}
    assert {"findplus.sqlite", "bike-tracker.sqlite"} <= names
