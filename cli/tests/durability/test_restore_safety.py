"""Restore: two in one second, the daemon lock, and a blocked checkpoint."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from findplus.cli import main
from findplus.config import get_settings
from findplus.db import backup, restore, runlock
from findplus.db.restore import RestoreError, restore_backup
from tests.durability._seed import seed_everything

NOW = datetime(2026, 9, 30, 12, 0, 0, 5, tzinfo=UTC)


@pytest.fixture
def good(session, tmp_db) -> Path:
    seed_everything(session, observations=4)
    session.commit()
    return backup.create_backup(
        Path(tmp_db), get_settings().effective_backup_dir, kind="manual", now=NOW
    ).path


def test_two_restores_in_one_second_keep_both_old_files(good) -> None:
    a = restore_backup(get_settings(), good, now=NOW)
    b = restore_backup(get_settings(), good, now=NOW + timedelta(microseconds=1))
    assert a.replaced_file.exists() and b.replaced_file.exists()
    assert a.replaced_file != b.replaced_file
    assert a.pre_restore_backup != b.pre_restore_backup and b.pre_restore_backup.exists()


def test_an_existing_kept_file_is_never_overwritten(good) -> None:
    first = restore_backup(get_settings(), good, now=NOW)
    marker = first.replaced_file.read_bytes()
    with pytest.raises(RestoreError, match="already exists"):
        restore_backup(get_settings(), good, now=NOW)
    assert first.replaced_file.read_bytes() == marker


def test_backups_in_the_same_second_do_not_replace_each_other(tmp_db, tmp_path) -> None:
    one = backup.create_backup(Path(tmp_db), tmp_path / "b", kind="manual", now=NOW)
    two = backup.create_backup(Path(tmp_db), tmp_path / "b", kind="manual", now=NOW)
    assert one.path != two.path and one.path.exists() and two.path.exists()


def test_the_daemon_lock_is_seen_by_a_second_process_view(tmp_path) -> None:
    held = runlock.acquire(tmp_path)
    assert held is not None
    assert runlock.is_held(tmp_path)
    assert runlock.acquire(tmp_path) is None
    held.close()
    assert not runlock.is_held(tmp_path)


def test_cli_restore_refuses_while_the_lock_is_held(good) -> None:
    state = get_settings().state_dir
    held = runlock.acquire(state)
    try:
        out = CliRunner().invoke(main, ["db", "restore", str(good)])
    finally:
        held.close()
    assert out.exit_code != 0 and "running" in out.output


def test_a_blocked_checkpoint_stops_the_restore_unless_forced(good, monkeypatch) -> None:
    monkeypatch.setattr(restore, "_checkpoint", lambda db: False)
    with pytest.raises(RestoreError, match="still has the database open"):
        restore_backup(get_settings(), good, now=NOW)
    assert restore_backup(get_settings(), good, force=True, now=NOW).replaced_file


def test_the_old_wal_goes_aside_with_the_kept_file(good, tmp_db) -> None:
    wal = Path(f"{tmp_db}-wal")
    wal.write_bytes(b"pending frames")
    result = restore_backup(get_settings(), good, force=True, now=NOW)
    assert Path(f"{result.replaced_file}-wal").read_bytes() == b"pending frames"
