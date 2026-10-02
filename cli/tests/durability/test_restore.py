"""`restore`: validates, backs up first, keeps the old file, refuses while running."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from findplus.config import get_settings
from findplus.db import backup
from findplus.db.migrate import current_revision, head_revision
from findplus.db.models import Device, LocationObservation
from findplus.db.restore import RestoreError, restore_backup, validate_backup
from findplus.db.session import session_scope
from tests.durability._seed import seed_everything
from tests.migration_0013_seed import seed_0012, setup

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _counts() -> tuple[int, int]:
    with session_scope() as s:
        return (
            s.scalar(select(func.count()).select_from(Device)),
            s.scalar(select(func.count()).select_from(LocationObservation)),
        )


@pytest.fixture
def seeded_backup(session, tmp_db) -> Path:
    seed_everything(session, observations=12)
    session.commit()
    return backup.create_backup(
        Path(tmp_db), get_settings().effective_backup_dir, kind="manual", now=NOW
    ).path


def test_restore_puts_the_backup_back_and_keeps_the_old_file(session, seeded_backup) -> None:
    with session_scope() as s:
        s.query(LocationObservation).delete()
    assert _counts() == (3, 0)
    result = restore_backup(get_settings(), seeded_backup, now=NOW)
    assert _counts() == (3, 12)
    assert result.replaced_file and result.replaced_file.exists()
    assert ".replaced-" in result.replaced_file.name
    assert result.pre_restore_backup and result.pre_restore_backup.exists()
    assert result.revision_after == head_revision() == current_revision()


def test_the_replaced_file_still_holds_what_was_there(session, seeded_backup) -> None:
    with session_scope() as s:
        s.query(LocationObservation).filter(LocationObservation.device_id == "d-shoes").delete()
    result = restore_backup(get_settings(), seeded_backup, now=NOW)
    old = sqlite3.connect(result.replaced_file)
    assert old.execute("SELECT count(*) FROM location_observations").fetchone()[0] == 0
    pre = sqlite3.connect(result.pre_restore_backup)
    assert pre.execute("SELECT count(*) FROM location_observations").fetchone()[0] == 0


def test_the_source_file_is_only_read(session, seeded_backup) -> None:
    before = seeded_backup.read_bytes()
    restore_backup(get_settings(), seeded_backup, now=NOW)
    assert seeded_backup.read_bytes() == before


def test_refuses_while_the_daemon_runs_unless_forced(session, seeded_backup) -> None:
    with pytest.raises(RestoreError, match="is running"):
        restore_backup(get_settings(), seeded_backup, daemon_running=lambda: True, now=NOW)
    assert _counts() == (3, 12)
    restore_backup(get_settings(), seeded_backup, daemon_running=lambda: True, force=True, now=NOW)


def test_refuses_a_file_that_is_not_a_database(tmp_db, tmp_path) -> None:
    junk = tmp_path / "junk.sqlite"
    junk.write_bytes(b"not sqlite at all" * 100)
    with pytest.raises(RestoreError, match="not a SQLite"):
        restore_backup(get_settings(), junk, now=NOW)


def test_refuses_a_sqlite_file_that_is_not_findplus(tmp_db, tmp_path) -> None:
    other = tmp_path / "other.sqlite"
    conn = sqlite3.connect(other)
    conn.execute("CREATE TABLE notes(a)")
    conn.commit()
    conn.close()
    with pytest.raises(RestoreError, match="not a Find\\+ database"):
        validate_backup(other)


def test_refuses_a_backup_from_a_newer_findplus(seeded_backup, tmp_path) -> None:
    newer = tmp_path / "newer.sqlite"
    newer.write_bytes(seeded_backup.read_bytes())
    conn = sqlite3.connect(newer)
    conn.execute("UPDATE alembic_version SET version_num='9999'")
    conn.commit()
    conn.close()
    with pytest.raises(RestoreError, match="newer Find\\+"):
        restore_backup(get_settings(), newer, now=NOW)
    assert _counts() == (3, 12)  # nothing changed


def test_refuses_a_damaged_backup_and_changes_nothing(seeded_backup, tmp_path) -> None:
    bad = tmp_path / "bad.sqlite"
    data = bytearray(seeded_backup.read_bytes())
    for i in range(4096 * 2, min(len(data), 4096 * 3)):
        data[i] = 0xCD
    bad.write_bytes(bytes(data))
    with pytest.raises(RestoreError):
        restore_backup(get_settings(), bad, now=NOW)
    assert _counts() == (3, 12)
    assert not list(get_settings().database_path.parent.glob("*.replaced-*"))


def test_restoring_an_older_schema_upgrades_it(tmp_db, tmp_path) -> None:
    (tmp_path / "old").mkdir()
    _cfg, url, engine = setup(tmp_path / "old", revision="0012")
    seed_0012(engine)
    engine.dispose()
    old_file = Path(url.removeprefix("sqlite:///"))
    result = restore_backup(get_settings(), old_file, now=NOW)
    assert result.revision_after == head_revision()
    assert _counts()[0] == 3  # the three seeded trackers survived the upgrade


def test_restore_into_a_missing_database_works(tmp_db, session, seeded_backup) -> None:
    session.get_bind().dispose()
    settings = get_settings()
    for suffix in ("", "-wal", "-shm"):
        Path(f"{settings.database_path}{suffix}").unlink(missing_ok=True)
    result = restore_backup(settings, seeded_backup, now=NOW)
    assert result.replaced_file is None and result.pre_restore_backup is None
    assert _counts() == (3, 12)


def test_a_file_with_a_known_revision_but_a_broken_schema_is_refused(
    session, seeded_backup, tmp_path
) -> None:
    broken = tmp_path / "broken.sqlite"
    backup.snapshot(seeded_backup, broken)
    conn = sqlite3.connect(broken)
    conn.execute("DROP TABLE alert_rules")
    conn.commit()
    conn.close()
    assert backup_check_ok(broken)
    with pytest.raises(RestoreError, match="alert_rules is missing"):
        validate_backup(broken)
    with pytest.raises(RestoreError):
        restore_backup(get_settings(), broken, now=NOW)
    assert _counts() == (3, 12)  # the live database was not touched


def test_an_older_backup_is_judged_by_its_own_schema(session, tmp_db) -> None:
    from findplus.db.restore import schema_problems

    assert schema_problems(Path(tmp_db), head_revision()) == []


def backup_check_ok(path: Path) -> bool:
    from findplus.db.integrity import check_database

    return check_database(path).ok
