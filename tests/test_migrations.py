"""Alembic migrations apply, reverse, and produce the indexes queries rely on."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from bike_tracker.db.migrate import current_revision, head_revision, is_up_to_date, upgrade_to_head
from bike_tracker.db.session import get_engine


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

    from bike_tracker.db.migrate import _config

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
