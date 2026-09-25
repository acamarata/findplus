"""Migration 0010: alert_deliveries retry (attempts, next_attempt_at, 'retrying').

Purpose : Prove attempts backfills to 1 for a pre-existing row, next_attempt_at
          is nullable, the widened CHECK accepts 'retrying', and the downgrade
          maps 'retrying' -> 'failed' before dropping both columns cleanly.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command

from findplus.db.migrate import get_alembic_config

NOW = "2026-09-22T00:00:00"


def _cfg(tmp_path: Path):
    db_path = tmp_path / "t.sqlite"
    return get_alembic_config(f"sqlite:///{db_path}"), db_path


def _engine(db_path: Path) -> sa.Engine:
    return sa.create_engine(f"sqlite:///{db_path}")


def _columns(db_path: Path, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(_engine(db_path)).get_columns(table)}


def _seed_rule_and_delivery(conn, rule_id: int, event_id: int, status: str = "sent") -> None:
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
    conn.execute(
        sa.text(
            "INSERT INTO alert_deliveries "
            "(rule_id, event_kind, event_id, channel, sent_at, status) "
            "VALUES (:rid, 'device', :eid, 'telegram', :now, :status)"
        ),
        {"rid": rule_id, "eid": event_id, "now": NOW, "status": status},
    )


def test_upgrade_adds_attempts_and_next_attempt_at(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0010")
    assert {"attempts", "next_attempt_at"} <= _columns(db_path, "alert_deliveries")


def test_existing_rows_backfill_attempts_to_one(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0009")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _seed_rule_and_delivery(conn, rule_id=1, event_id=10)

    command.upgrade(cfg, "0010")
    with engine.begin() as conn:
        row = conn.execute(
            sa.text("SELECT attempts, next_attempt_at FROM alert_deliveries WHERE rule_id = 1")
        ).one()
    assert row.attempts == 1
    assert row.next_attempt_at is None


def test_retrying_status_is_accepted_after_upgrade(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0010")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _seed_rule_and_delivery(conn, rule_id=1, event_id=10, status="retrying")
        status = conn.execute(
            sa.text("SELECT status FROM alert_deliveries WHERE rule_id = 1")
        ).scalar_one()
    assert status == "retrying"


def test_downgrade_maps_retrying_to_failed_and_drops_columns(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0010")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _seed_rule_and_delivery(conn, rule_id=1, event_id=10, status="retrying")

    command.downgrade(cfg, "0009")
    assert {"attempts", "next_attempt_at"}.isdisjoint(_columns(db_path, "alert_deliveries"))
    with engine.begin() as conn:
        status = conn.execute(
            sa.text("SELECT status FROM alert_deliveries WHERE rule_id = 1")
        ).scalar_one()
    assert status == "failed"

    command.upgrade(cfg, "0010")
    with engine.begin() as conn:
        version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "0010"


def test_full_head_upgrade_reaches_at_least_0010(tmp_path: Path) -> None:
    """ "head" moves as later migrations land (0011 added the delivery
    `target` column) -- this only proves 0010 is still on the path to head,
    not that it IS head. test_migration_0011.py pins the current head."""
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "head")
    engine = _engine(db_path)
    with engine.begin() as conn:
        version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version != "0009"
    assert {"attempts", "next_attempt_at"} <= _columns(db_path, "alert_deliveries")
