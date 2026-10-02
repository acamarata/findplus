"""Health checks, the startup verdict, and the read-only database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from findplus.config import get_settings
from findplus.db import integrity
from tests.durability._seed import seed_everything


@pytest.fixture(autouse=True)
def _fresh_health():
    integrity.reset_health()
    yield
    integrity.reset_health()


def _damage(path: Path) -> None:
    """Overwrite a page in the middle of the file with garbage."""
    data = bytearray(path.read_bytes())
    for i in range(4096 * 2, 4096 * 3):
        data[i] = 0xAB
    path.write_bytes(bytes(data))


def test_a_sound_database_passes_every_check(session, tmp_db) -> None:
    seed_everything(session)
    session.commit()
    report = integrity.check_database(Path(tmp_db), full=True)
    assert report.ok and report.problems == []


def test_a_missing_file_is_reported_not_raised(tmp_path) -> None:
    report = integrity.check_database(tmp_path / "nope.sqlite")
    assert not report.ok and "does not exist" in report.problems[0]


def test_garbage_is_reported_as_damage(tmp_path) -> None:
    bad = tmp_path / "bad.sqlite"
    bad.write_bytes(b"this is not a database" * 500)
    report = integrity.check_database(bad, full=True)
    assert not report.ok and report.unreadable


def test_a_damaged_page_fails_the_checks(session, tmp_db) -> None:
    seed_everything(session, observations=400)
    session.commit()
    session.get_bind().dispose()
    sqlite3.connect(tmp_db).execute("PRAGMA wal_checkpoint(TRUNCATE)").close()
    _damage(Path(tmp_db))
    report = integrity.check_database(Path(tmp_db), full=True)
    assert not report.ok


def test_a_foreign_key_break_is_found(session, tmp_db) -> None:
    seed_everything(session)
    session.commit()
    conn = sqlite3.connect(tmp_db)
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("DELETE FROM devices WHERE device_id='d-shoes'")
    conn.commit()
    conn.close()
    report = integrity.check_database(Path(tmp_db), full=True)
    assert report.foreign_keys and "missing" in report.foreign_keys[0]
    assert not integrity.check_database(Path(tmp_db)).problems  # quick_check alone does not look


def test_startup_check_records_the_verdict(tmp_path) -> None:
    bad = tmp_path / "bad.sqlite"
    bad.write_bytes(b"x" * 5000)
    health = integrity.startup_check(bad)
    assert not health.ok and health.read_only and integrity.current_health() is health
    integrity.reset_health()
    assert integrity.current_health().ok


def test_new_connections_are_query_only_after_a_failed_startup(tmp_db, monkeypatch) -> None:
    from sqlalchemy import text

    from findplus.db.session import get_engine

    monkeypatch.setattr(integrity, "_HEALTH", integrity.DbHealth(False, ("damaged",)))
    get_engine.cache_clear()
    with get_engine().connect() as conn:
        assert conn.execute(text("PRAGMA query_only")).scalar() == 1
        with pytest.raises(Exception, match="readonly"):
            conn.execute(text("INSERT INTO settings(key, value, updated_at) VALUES ('a','b',0)"))


def test_synchronous_is_full_and_wal_is_kept(tmp_db) -> None:
    from sqlalchemy import text

    from findplus.db.session import get_engine

    with get_engine().connect() as conn:
        assert conn.execute(text("PRAGMA synchronous")).scalar() == 2  # FULL
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
    assert get_settings().database_path.exists()


def test_status_reports_the_database_verdict(client, monkeypatch) -> None:
    assert client.get("/api/status").json()["database"] == {"ok": True, "problems": []}
    monkeypatch.setattr(integrity, "_HEALTH", integrity.DbHealth(False, ("page 3 is damaged",)))
    body = client.get("/api/status").json()
    assert body["database"] == {"ok": False, "problems": ["page 3 is damaged"]}
