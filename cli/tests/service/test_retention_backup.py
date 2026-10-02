"""The daily backup rides the retention loop: startup, daily, never blocking pruning."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest

from findplus.config import get_settings
from findplus.db import backup, integrity
from findplus.db.session import session_scope
from findplus.service import retention
from tests.durability._seed import seed_everything


def _backups() -> list:
    return backup.list_backups(get_settings().effective_backup_dir)


@pytest.fixture
def seeded(tmp_db):
    integrity.reset_health()
    with session_scope() as s:
        seed_everything(s)
    return tmp_db


def test_startup_backs_up_when_none_exists_then_not_again(seeded) -> None:
    assert retention.backup_cycle(startup=True) is not None
    assert len(_backups()) == 1
    assert retention.backup_cycle(startup=True) is None
    assert len(_backups()) == 1


def test_startup_backs_up_when_the_last_is_over_a_day_old(seeded) -> None:
    old = datetime.now(UTC) - timedelta(hours=25)
    backup.create_backup(get_settings().database_path, get_settings().effective_backup_dir, now=old)
    assert retention.backup_cycle(startup=True) is not None
    assert len(_backups()) == 2


def test_a_damaged_database_is_not_backed_up(seeded, monkeypatch) -> None:
    monkeypatch.setattr(integrity, "_HEALTH", integrity.DbHealth(False, ("damaged",)))
    assert retention.backup_cycle(startup=True) is None
    assert _backups() == []


def test_the_loop_backs_up_and_a_failed_backup_never_stops_pruning(
    seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran: list[str] = []
    monkeypatch.setattr(retention, "run_once", lambda state_dir=None: ran.append("prune"))

    def failing(state_dir=None, *, startup=False):
        ran.append("backup")
        raise RuntimeError("disk full")

    monkeypatch.setattr(retention, "backup_cycle", failing)
    waits: list[float] = []

    def _wait(self, timeout=None):
        waits.append(timeout)
        return len(waits) >= 2

    monkeypatch.setattr(threading.Event, "wait", _wait)
    monkeypatch.setattr(threading.Event, "is_set", lambda self: len(waits) >= 2)
    retention.RetentionScheduler().run_forever()
    assert ran == ["prune", "backup", "prune", "backup"]


def test_the_loop_makes_one_backup_on_its_first_pass(
    seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(retention, "run_once", lambda state_dir=None: None)
    waits: list[float] = []
    monkeypatch.setattr(threading.Event, "wait", lambda self, timeout=None: waits.append(1) or True)
    monkeypatch.setattr(threading.Event, "is_set", lambda self: len(waits) >= 1)
    retention.RetentionScheduler().run_forever()
    assert len(_backups()) == 1
