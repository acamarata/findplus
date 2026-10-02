"""Online backups: consistent while writing, verified, private, rotated, secret-free."""

from __future__ import annotations

import os
import sqlite3
import stat
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from findplus.config import get_settings
from findplus.db import backup
from findplus.db.integrity import check_database
from findplus.db.session import session_scope
from findplus.ingest import ingest_observations
from tests.conftest import make_observation
from tests.durability._seed import seed_everything

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _count(path: Path) -> int:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT count(*) FROM location_observations").fetchone()[0]
    finally:
        conn.close()


def test_backup_is_a_verified_copy_with_the_rows(session, tmp_db) -> None:
    seed_everything(session)
    session.commit()
    info = backup.create_backup(Path(tmp_db), get_settings().effective_backup_dir, now=NOW)
    assert info.path.name == "findplus-20260930-120000.sqlite" and info.kind == "auto"
    assert check_database(info.path, full=True).ok
    assert _count(info.path) == 12


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_backup_is_0600_in_a_0700_directory(session, tmp_db) -> None:
    seed_everything(session)
    session.commit()
    directory = get_settings().effective_backup_dir
    info = backup.create_backup(Path(tmp_db), directory, now=NOW)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(info.path.stat().st_mode) == 0o600


def test_a_loose_directory_is_tightened(tmp_path) -> None:
    loose = tmp_path / "b"
    loose.mkdir(mode=0o755)
    backup.prepare_dir(loose)
    assert stat.S_IMODE(loose.stat().st_mode) == 0o700


def test_the_backup_directory_holds_only_database_files(session, tmp_db) -> None:
    state = get_settings().state_dir
    state.mkdir(parents=True, exist_ok=True)
    (state / "secrets.json").write_text('{"aas_token": "SECRET-TOKEN-VALUE"}')
    seed_everything(session)
    session.commit()
    info = backup.create_backup(Path(tmp_db), get_settings().effective_backup_dir, now=NOW)
    names = {p.name for p in info.path.parent.iterdir()}
    assert names == {info.path.name}
    assert b"SECRET-TOKEN-VALUE" not in info.path.read_bytes()


def test_a_missing_database_is_a_plain_error(tmp_path) -> None:
    with pytest.raises(backup.BackupError, match="no database"):
        backup.create_backup(tmp_path / "none.sqlite", tmp_path / "b", now=NOW)


def test_a_backup_taken_while_ingest_writes_is_whole(session, tmp_db) -> None:
    seed_everything(session, observations=5)
    session.commit()
    stop = threading.Event()
    errors: list[Exception] = []

    def writer() -> None:
        n = 0
        while not stop.is_set():
            try:
                with session_scope() as s:
                    ingest_observations(
                        s,
                        [
                            make_observation(
                                device_id="d-shoes", minutes=2000 + n, lat=41.5 + n * 1e-5
                            )
                        ],
                        fetched_at=NOW,
                    )
                n += 1
            except Exception as exc:  # pragma: no cover - would fail the test below
                errors.append(exc)
                return

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        infos = [
            backup.create_backup(
                Path(tmp_db),
                get_settings().effective_backup_dir,
                kind="manual",
                now=NOW + timedelta(seconds=i),
            )
            for i in range(3)
        ]
    finally:
        stop.set()
        thread.join()
    assert not errors
    counts = [_count(i.path) for i in infos]
    assert all(check_database(i.path, full=True).ok for i in infos)
    assert counts == sorted(counts) and counts[0] >= 5


def test_due_when_none_or_older_than_a_day(tmp_path) -> None:
    d = tmp_path / "b"
    assert backup.backup_due(d, NOW)
    db = tmp_path / "x.sqlite"
    sqlite3.connect(db).execute("CREATE TABLE t(a)").connection.commit()
    backup.create_backup(db, d, now=NOW)
    assert not backup.backup_due(d, NOW + timedelta(hours=23, minutes=59))
    assert backup.backup_due(d, NOW + timedelta(hours=24))
    assert backup.backup_due(d, NOW + timedelta(hours=21), min_age=timedelta(hours=20))


def _make_many(tmp_path: Path, stamps: list[datetime], kind: str = "auto") -> Path:
    db = tmp_path / "x.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t(a)")
    conn.commit()
    conn.close()
    d = tmp_path / "b"
    for s in stamps:
        backup.create_backup(db, d, kind=kind, now=s)
    return d


def test_rotation_keeps_seven_daily_and_four_weekly(tmp_path) -> None:
    # Two backups a day for 60 days.
    stamps = [NOW - timedelta(days=i, hours=h) for i in range(60) for h in (0, 5)]
    d = _make_many(tmp_path, stamps)
    removed = backup.rotate(d, 7, 4)
    kept = backup.list_backups(d)
    assert len(kept) == 7 + 4
    assert len(removed) == 120 - 11
    days = [b.taken_at.date() for b in kept[:7]]
    assert days == [(NOW - timedelta(days=i)).date() for i in range(7)]
    assert all(b.taken_at.hour == 12 for b in kept[:7])  # the newest of each day
    weeks = {b.taken_at.isocalendar()[:2] for b in kept[7:]}
    assert len(weeks) == 4


def test_rotation_never_touches_manual_or_prerestore_backups(tmp_path) -> None:
    d = _make_many(tmp_path, [NOW - timedelta(days=i) for i in range(30)])
    db = tmp_path / "x.sqlite"
    manual = backup.create_backup(db, d, kind="manual", now=NOW - timedelta(days=90))
    pre = backup.create_backup(db, d, kind="prerestore", now=NOW - timedelta(days=91))
    backup.rotate(d, 7, 4)
    assert manual.path.exists() and pre.path.exists()


def test_rotation_with_nothing_to_remove(tmp_path) -> None:
    d = _make_many(tmp_path, [NOW, NOW - timedelta(days=1)])
    assert backup.rotate(d, 7, 4) == []
    assert backup.rotate(tmp_path / "missing", 7, 4) == []


def test_run_scheduled_backs_up_once_per_day(session, tmp_db) -> None:
    seed_everything(session)
    session.commit()
    settings = get_settings()
    first = backup.run_scheduled(settings, now=NOW)
    assert first is not None
    assert backup.run_scheduled(settings, now=NOW + timedelta(hours=2)) is None
    assert backup.run_scheduled(settings, now=NOW + timedelta(hours=25)) is not None
    assert backup.run_scheduled(settings, now=NOW + timedelta(hours=2), force=True) is not None


def test_a_chosen_folder_is_never_chmodded(tmp_db, monkeypatch, tmp_path) -> None:
    """Only the findplus-backups subfolder is made private; the owner's folder is left alone."""
    import stat

    from findplus.config import get_settings, reset_settings_cache

    chosen = tmp_path / "Documents"
    chosen.mkdir(mode=0o755)
    chosen.chmod(0o755)
    monkeypatch.setenv("FINDPLUS_BACKUP_DIR", str(chosen))
    reset_settings_cache()
    directory = get_settings().effective_backup_dir
    assert directory == chosen / "findplus-backups"
    backup.create_backup(Path(tmp_db), directory)
    assert stat.S_IMODE(chosen.stat().st_mode) == 0o755
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_an_unusable_folder_is_a_backup_error(tmp_path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(backup.BackupError):
        backup.prepare_dir(blocker / "sub")


def test_tilde_in_the_backup_directory_is_expanded(tmp_db, monkeypatch) -> None:
    from findplus.config import get_settings, reset_settings_cache

    monkeypatch.setenv("FINDPLUS_BACKUP_DIR", "~/findplus-test-backups")
    reset_settings_cache()
    directory = get_settings().effective_backup_dir
    assert directory.is_absolute() and "~" not in str(directory)
    assert directory == Path.home() / "findplus-test-backups" / "findplus-backups"


def test_a_stray_file_or_dangling_link_does_not_break_listing(tmp_path) -> None:
    (tmp_path / "findplus-20261399-000000.sqlite").write_text("x")
    (tmp_path / "findplus-20260930-120000.sqlite").symlink_to(tmp_path / "nowhere")
    good = tmp_path / "findplus-20260929-120000.sqlite"
    good.write_text("x")
    assert [b.path for b in backup.list_backups(tmp_path)] == [good]
    assert backup.rotate(tmp_path) == []


def test_a_backup_stamped_in_the_future_does_not_stop_backups(tmp_path) -> None:
    now = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
    (tmp_path / "findplus-20270101-000000.sqlite").write_text("x")
    assert backup.backup_due(tmp_path, now)
    (tmp_path / "findplus-20260930-110000.sqlite").write_text("x")
    assert not backup.backup_due(tmp_path, now)
