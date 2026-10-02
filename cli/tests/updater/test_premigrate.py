"""db/premigrate.py: a new version's first start backs up the old schema before upgrading."""

from __future__ import annotations

from pathlib import Path

from findplus.db.backup import list_backups
from findplus.db.premigrate import backup_before_migrate


def _settings(tmp_path: Path, monkeypatch):
    from findplus.config import get_settings, reset_settings_cache
    from findplus.db.session import get_engine

    monkeypatch.setenv("FINDPLUS_DATABASE_PATH", str(tmp_path / "old.sqlite"))
    monkeypatch.setenv("FINDPLUS_STATE_DIR", str(tmp_path / "state"))
    reset_settings_cache()
    get_engine.cache_clear()
    return get_settings()


def test_an_older_schema_is_backed_up_before_the_upgrade(tmp_path, monkeypatch) -> None:
    from findplus.db.migrate import run_migrations, upgrade_to_head

    s = _settings(tmp_path, monkeypatch)
    run_migrations(s.database_url, "0012")  # the schema an older Find+ left behind
    path = backup_before_migrate(s)
    assert path is not None and path.name.startswith("findplus-preupdate-")
    upgrade_to_head(s.database_url)
    assert backup_before_migrate(s) is None  # up to date: no second copy
    assert [b.kind for b in list_backups(s.effective_backup_dir)] == ["preupdate"]


def test_a_fresh_install_takes_no_backup(tmp_path, monkeypatch) -> None:
    s = _settings(tmp_path, monkeypatch)
    assert backup_before_migrate(s) is None
    assert not s.effective_backup_dir.exists()
