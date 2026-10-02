"""Restore must work over a damaged live database (the case it exists for)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from findplus.cli import main
from findplus.config import get_settings
from findplus.db import backup
from findplus.db.integrity import check_database
from findplus.db.restore import restore_backup
from findplus.db.session import get_engine
from tests.durability._damage import add_bulk, damage
from tests.durability._seed import seed_everything

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


@pytest.fixture
def damaged(session, tmp_db) -> tuple[Path, Path]:
    seed_everything(session, observations=12)
    session.commit()
    good = backup.create_backup(
        Path(tmp_db), get_settings().effective_backup_dir, kind="manual", now=NOW
    ).path
    get_engine().dispose()
    db = Path(tmp_db)
    add_bulk(db)
    damage(db)
    assert not check_database(db).ok
    return db, good


def test_restore_over_a_damaged_file_works_and_keeps_it(damaged) -> None:
    db, good = damaged
    result = restore_backup(get_settings(), good, now=NOW)
    assert check_database(db).ok
    assert result.pre_restore_backup is None  # the damaged copy cannot be backed up
    assert result.replaced_file and result.replaced_file.exists()
    assert not check_database(result.replaced_file).ok  # kept as it was found


def test_cli_restore_over_a_damaged_file(damaged) -> None:
    db, good = damaged
    out = CliRunner().invoke(main, ["db", "restore", str(good)])
    assert out.exit_code == 0, out.output
    assert "Restored from" in out.output
    assert check_database(db).ok


def test_cli_prints_plain_words_when_a_backup_fails(tmp_db, monkeypatch) -> None:
    def boom(*a, **k):
        raise backup.BackupError("The new backup did not pass its check: x")

    monkeypatch.setattr("findplus.db.restore.restore_backup", boom)
    out = CliRunner().invoke(main, ["db", "restore", tmp_db])
    assert out.exit_code != 0
    assert "Traceback" not in out.output and "did not pass its check" in out.output
