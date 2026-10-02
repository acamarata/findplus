"""`findplus doctor` database checks, and a daemon that starts on a damaged file."""

from __future__ import annotations

import json
import os
import stat
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from findplus.cli import cmd_serve
from findplus.cli.doctor import doctor_cmd
from findplus.cli.doctor_db import check_db_backups, check_db_integrity, repair_backup_perms
from findplus.config import get_settings
from findplus.db import backup, integrity
from findplus.db.session import get_engine, session_scope
from tests.durability._seed import seed_everything


@pytest.fixture
def seeded(tmp_db):
    integrity.reset_health()
    with session_scope() as s:
        seed_everything(s)
    return tmp_db


def _checks(*args: str) -> dict:
    res = CliRunner().invoke(doctor_cmd, ["--json", *args])
    return {c["name"]: c for c in json.loads(res.output)}


def test_doctor_lists_both_database_checks(seeded) -> None:
    checks = _checks()
    assert checks["db_integrity"]["passed"] and "sound" in checks["db_integrity"]["detail"]
    assert checks["db_backups"]["passed"] and "No backup yet" in checks["db_backups"]["detail"]


def test_doctor_fails_integrity_and_points_at_restore(seeded) -> None:
    path = get_settings().database_path
    get_engine().dispose()
    for suffix in ("-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)
    path.write_bytes(b"x" * 9000)
    check = check_db_integrity(get_settings())
    assert not check.passed and "findplus db restore" in check.detail and not check.repairable


def test_doctor_flags_a_stale_backup(seeded) -> None:
    settings = get_settings()
    old = datetime.now(UTC) - timedelta(days=5)
    backup.create_backup(settings.database_path, settings.effective_backup_dir, now=old)
    check = check_db_backups(settings)
    assert not check.passed and "5 days old" in check.detail
    backup.create_backup(settings.database_path, settings.effective_backup_dir)
    assert check_db_backups(settings).passed


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_loose_backup_permissions_fail_and_repair(seeded) -> None:
    settings = get_settings()
    info = backup.create_backup(settings.database_path, settings.effective_backup_dir)
    info.path.chmod(0o644)
    check = check_db_backups(settings)
    assert not check.passed and check.repairable
    repair_backup_perms(settings)
    assert stat.S_IMODE(info.path.stat().st_mode) == 0o600
    assert check_db_backups(settings).passed


def _damage(path: Path) -> bytes:
    get_engine().dispose()
    for suffix in ("-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)
    path.write_bytes(b"this was a database once" * 400)
    return path.read_bytes()


def test_startup_on_a_damaged_file_goes_read_only_and_leaves_it_alone(seeded) -> None:
    settings = get_settings()
    before = _damage(settings.database_path)
    cmd_serve._prep_or_read_only(settings)
    assert not integrity.current_health().ok
    assert settings.database_path.read_bytes() == before  # not migrated, not deleted


def test_startup_on_a_sound_file_upgrades_and_stays_healthy(seeded) -> None:
    cmd_serve._prep_or_read_only(get_settings())
    assert integrity.current_health().ok


def test_a_first_run_with_no_database_is_healthy(tmp_path, monkeypatch) -> None:
    from findplus.config import reset_settings_cache

    monkeypatch.setenv("FINDPLUS_STATE_DIR", str(tmp_path / "s"))
    monkeypatch.setenv("FINDPLUS_DATABASE_PATH", str(tmp_path / "s" / "new.sqlite"))
    reset_settings_cache()
    get_engine.cache_clear()
    integrity.reset_health()
    cmd_serve._prep_or_read_only(get_settings())
    assert integrity.current_health().ok and (tmp_path / "s" / "new.sqlite").exists()
    get_engine.cache_clear()


def test_a_damaged_daemon_starts_no_workers(seeded, monkeypatch) -> None:
    started: list[str] = []
    monkeypatch.setattr(
        cmd_serve, "_start_worker", lambda w, name: started.append(name) or (w, None)
    )
    monkeypatch.setattr(cmd_serve, "_stop_workers", lambda ws: None)

    class _Srv:
        should_exit = False

    def _fake_uvicorn(*a):
        thread = threading.Thread(target=lambda: None)
        thread.start()
        return _Srv(), thread

    monkeypatch.setattr(cmd_serve, "_start_uvicorn", _fake_uvicorn)
    monkeypatch.setattr(cmd_serve, "_wait_for_stop", lambda ev, th: 0)
    settings = get_settings()
    monkeypatch.setattr(integrity, "_HEALTH", integrity.DbHealth(False, ("damaged",)))
    cmd_serve._run_server(settings, "127.0.0.1", 8999, False, threading.Event())
    assert started == []
    integrity.reset_health()
    cmd_serve._run_server(settings, "127.0.0.1", 8999, False, threading.Event())
    assert started == ["poller", "retention", "digest"]
