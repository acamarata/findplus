"""Alembic migrations apply, reverse, and produce the indexes queries rely on."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from findplus.db.migrate import current_revision, head_revision, is_up_to_date, upgrade_to_head
from findplus.db.session import get_engine


def _url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'm.sqlite'}"


def _names(db: Path, kind: str) -> set[str]:
    con = sqlite3.connect(db)
    try:
        return {
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type=? AND name NOT LIKE 'sqlite_%'", (kind,)
            )
        }
    finally:
        con.close()


def test_upgrade_creates_every_required_table(tmp_path: Path) -> None:
    get_engine.cache_clear()
    upgrade_to_head(_url(tmp_path))
    tables = _names(tmp_path / "m.sqlite", "table")
    assert {"devices", "location_observations", "poll_runs", "settings"} <= tables


def test_upgrade_creates_the_query_indexes(tmp_path: Path) -> None:
    get_engine.cache_clear()
    upgrade_to_head(_url(tmp_path))
    indexes = _names(tmp_path / "m.sqlite", "index")
    assert {"ix_obs_device_observed", "ix_obs_observed", "ix_pollrun_started"} <= indexes


def test_upgrade_is_idempotent(tmp_path: Path) -> None:
    get_engine.cache_clear()
    url = _url(tmp_path)
    upgrade_to_head(url)
    first = current_revision(url)
    upgrade_to_head(url)
    assert current_revision(url) == first


def test_reports_head_after_upgrade(tmp_path: Path) -> None:
    get_engine.cache_clear()
    url = _url(tmp_path)
    upgrade_to_head(url)
    assert current_revision(url) == head_revision()
    assert is_up_to_date(url) is True


def test_unique_constraint_on_observation_identity_exists(tmp_path: Path) -> None:
    """The dedup guarantee must be enforced by the database, not only by code."""
    get_engine.cache_clear()
    url = _url(tmp_path)
    upgrade_to_head(url)
    con = sqlite3.connect(tmp_path / "m.sqlite")
    try:
        ddl = con.execute(
            "SELECT sql FROM sqlite_master WHERE name='location_observations'"
        ).fetchone()[0]
    finally:
        con.close()
    assert "uq_observation_identity" in ddl


def test_downgrade_removes_tables(tmp_path: Path) -> None:
    from alembic import command

    from findplus.db.migrate import _config

    get_engine.cache_clear()
    url = _url(tmp_path)
    upgrade_to_head(url)
    cfg = _config(url)
    engine = get_engine(url)
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "base")
    tables = _names(tmp_path / "m.sqlite", "table")
    assert "location_observations" not in tables


# --------------------------------------------------------- package-bundled migrations
def test_migrate_to_head_from_empty(tmp_path: Path) -> None:
    from sqlalchemy import create_engine, inspect

    from findplus.db.migrate import run_migrations

    url = f"sqlite:///{tmp_path}/t.db"
    run_migrations(url, "head")
    assert "devices" in inspect(create_engine(url)).get_table_names()


def test_single_head() -> None:
    from alembic.script import ScriptDirectory

    from findplus.db.migrate import get_alembic_config

    cfg = get_alembic_config("sqlite://")
    assert len(ScriptDirectory.from_config(cfg).get_heads()) == 1


def test_migrate_down_to_base(tmp_path: Path) -> None:
    from sqlalchemy import create_engine, inspect

    from findplus.db.migrate import run_migrations

    url = f"sqlite:///{tmp_path}/t.db"
    run_migrations(url, "head")
    run_migrations(url, "base")
    # Alembic keeps its own bookkeeping table (empty) after a downgrade to base;
    # every schema table must be gone.
    tables = set(inspect(create_engine(url)).get_table_names()) - {"alembic_version"}
    assert tables == set()


# ------------------------------------------------------------------ 0007 labels
def test_0007_backfills_every_device_a_palette_color(tmp_path: Path, monkeypatch) -> None:
    """The migration's inline formula and `labels.palette_color_for` agree.

    The revision keeps its own copy of the palette and the hash (an Alembic
    revision has to stay runnable long after labels.py moves on), so a device
    created through the app must land on exactly the colour the backfill would
    have given it.
    """
    from findplus.config import get_settings, reset_settings_cache
    from findplus.db.session import session_scope
    from findplus.ingest import upsert_device
    from findplus.labels import palette_color_for

    monkeypatch.setenv("FINDPLUS_DATABASE_PATH", str(tmp_path / "m.sqlite"))
    monkeypatch.setenv("FINDPLUS_STATE_DIR", str(tmp_path / "state"))
    reset_settings_cache()
    get_engine.cache_clear()
    get_settings()
    upgrade_to_head()
    with session_scope() as session:
        device = upsert_device(session, "TAG-palette", "Moto Tag 2")
        assert device.color == palette_color_for("TAG-palette")
    reset_settings_cache()
    get_engine.cache_clear()
