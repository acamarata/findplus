"""Migration 0011: alert_deliveries.target, widened uq_alert_deliveries_dedup.

Purpose : Prove `target` backfills to '' for a pre-existing row (never NULL,
          per the migration's own docstring -- NULL would defeat the unique
          constraint's race-safety net for single-target channels), the
          widened UNIQUE constraint accepts two rows that differ only by
          target, and rejects an exact duplicate (same target twice), and
          the downgrade drops the column and narrows the constraint back.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.exc import IntegrityError

from findplus.db.migrate import get_alembic_config

NOW = "2026-09-25T00:00:00"


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


def _insert_delivery(conn, rule_id: int, event_id: int, target: str | None = None) -> None:
    cols = "rule_id, event_kind, event_id, channel, sent_at, status"
    params = {"rid": rule_id, "eid": event_id, "now": NOW}
    values = "(:rid, 'device', :eid, 'telegram', :now, 'sent'"
    if target is not None:
        cols += ", target"
        params["target"] = target
        values += ", :target)"
    else:
        values += ")"
    conn.execute(sa.text(f"INSERT INTO alert_deliveries ({cols}) VALUES {values}"), params)


def test_upgrade_adds_target_column(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0011")
    assert "target" in _columns(db_path, "alert_deliveries")


def test_existing_rows_backfill_target_to_empty_string_not_null(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0010")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _seed_rule(conn, rule_id=1)
        _insert_delivery(conn, rule_id=1, event_id=10)

    command.upgrade(cfg, "0011")
    with engine.begin() as conn:
        target = conn.execute(
            sa.text("SELECT target FROM alert_deliveries WHERE rule_id = 1")
        ).scalar_one()
    assert target == ""
    assert target is not None


def test_unique_constraint_allows_two_targets_same_event(tmp_path: Path) -> None:
    """The whole point of 0011: one telegram rule fanning out to two chats
    produces two rows for the same (rule, event, channel), told apart only
    by target."""
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0011")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _seed_rule(conn, rule_id=1)
        _insert_delivery(conn, rule_id=1, event_id=10, target="111")
        _insert_delivery(conn, rule_id=1, event_id=10, target="222")
        count = conn.execute(
            sa.text("SELECT COUNT(*) FROM alert_deliveries WHERE rule_id = 1")
        ).scalar_one()
    assert count == 2


def test_unique_constraint_still_rejects_an_exact_duplicate(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0011")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _seed_rule(conn, rule_id=1)
        _insert_delivery(conn, rule_id=1, event_id=10, target="111")
    with engine.begin() as conn, pytest.raises(IntegrityError):
        _insert_delivery(conn, rule_id=1, event_id=10, target="111")


def test_downgrade_drops_target_and_narrows_constraint(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0011")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _seed_rule(conn, rule_id=1)
        _insert_delivery(conn, rule_id=1, event_id=10, target="111")

    command.downgrade(cfg, "0010")
    assert "target" not in _columns(db_path, "alert_deliveries")

    command.upgrade(cfg, "0011")
    with engine.begin() as conn:
        version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "0011"


def test_full_head_upgrade_reaches_at_least_0011(tmp_path: Path) -> None:
    """ "head" moves as later migrations land (0012 added alert_rules.
    telegram_targets) -- this only proves 0011 is still on the path to head,
    not that it IS head. test_migration_0012.py pins the current head."""
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "head")
    engine = _engine(db_path)
    with engine.begin() as conn:
        version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version not in ("0009", "0010")
    assert "target" in _columns(db_path, "alert_deliveries")
