"""Migration 0012: alert_rules.telegram_targets (per-rule Telegram subset).

Purpose : Prove the column is nullable and defaults every existing row to
          NULL ("every saved target", the pre-migration behaviour -- not
          "" as 0011's own `target` column does, since NULL and "" are
          deliberately different values here), that an explicit value
          round-trips, and that the downgrade drops the column cleanly.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command

from findplus.db.migrate import get_alembic_config

NOW = "2026-09-26T00:00:00"


def _cfg(tmp_path: Path):
    db_path = tmp_path / "t.sqlite"
    return get_alembic_config(f"sqlite:///{db_path}"), db_path


def _engine(db_path: Path) -> sa.Engine:
    return sa.create_engine(f"sqlite:///{db_path}")


def _columns(db_path: Path, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(_engine(db_path)).get_columns(table)}


def _seed_rule(conn, rule_id: int) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO devices (device_id, name, is_tracked, first_seen_at, last_seen_at) "
            "VALUES (:id, 'Tag', 0, :now, :now)"
        ),
        {"id": f"dev{rule_id}", "now": NOW},
    )
    conn.execute(
        sa.text(
            "INSERT INTO alert_rules (id, name, device_id, on_enter, on_exit, channels, "
            "cooldown_minutes, enabled, also_notify_members, created_at) "
            "VALUES (:rid, :name, :dev, 1, 1, 'telegram', 30, 1, 0, :now)"
        ),
        {"rid": rule_id, "name": f"r{rule_id}", "dev": f"dev{rule_id}", "now": NOW},
    )


def test_upgrade_adds_nullable_telegram_targets_column(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0012")
    cols = {c["name"]: c for c in sa.inspect(_engine(db_path)).get_columns("alert_rules")}
    assert "telegram_targets" in cols
    assert cols["telegram_targets"]["nullable"] is True


def test_existing_rows_backfill_to_null_not_empty_string(tmp_path: Path) -> None:
    """Unlike 0011's `target` column (backfills to ''), an existing rule must
    keep meaning "every saved target" -- NULL, not the distinct "explicit
    empty" value this same migration introduces."""
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0011")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _seed_rule(conn, rule_id=1)

    command.upgrade(cfg, "0012")
    with engine.begin() as conn:
        value = conn.execute(
            sa.text("SELECT telegram_targets FROM alert_rules WHERE id = 1")
        ).scalar_one()
    assert value is None


def test_explicit_value_round_trips(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0012")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _seed_rule(conn, rule_id=1)
        conn.execute(
            sa.text("UPDATE alert_rules SET telegram_targets = :v WHERE id = 1"),
            {"v": "111,-100222"},
        )
    with engine.begin() as conn:
        value = conn.execute(
            sa.text("SELECT telegram_targets FROM alert_rules WHERE id = 1")
        ).scalar_one()
    assert value == "111,-100222"


def test_explicit_empty_string_is_distinct_from_null(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0012")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _seed_rule(conn, rule_id=1)
        conn.execute(
            sa.text("UPDATE alert_rules SET telegram_targets = '' WHERE id = 1"),
        )
    with engine.begin() as conn:
        value = conn.execute(
            sa.text("SELECT telegram_targets FROM alert_rules WHERE id = 1")
        ).scalar_one()
    assert value == ""
    assert value is not None


def test_downgrade_drops_the_column(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0012")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _seed_rule(conn, rule_id=1)

    command.downgrade(cfg, "0011")
    assert "telegram_targets" not in _columns(db_path, "alert_rules")

    command.upgrade(cfg, "0012")
    with engine.begin() as conn:
        version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "0012"


def test_full_head_upgrade_reaches_0012(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "head")
    engine = _engine(db_path)
    with engine.begin() as conn:
        version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "0012"
