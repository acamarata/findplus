"""Migration 0005: groups, device_group, group_place_events, alert_rules, alert_deliveries.

Purpose : Prove the schema round-trips, every CHECK/UNIQUE constraint fires, and
          ON DELETE CASCADE removes device_group rows when a group is deleted.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command

from findplus.db.migrate import get_alembic_config

NOW = "2026-09-19T00:00:00"

_TABLES = {"groups", "device_group", "group_place_events", "alert_rules", "alert_deliveries"}


def _cfg(tmp_path: Path):
    db_path = tmp_path / "t.sqlite"
    return get_alembic_config(f"sqlite:///{db_path}"), db_path


def _engine(db_path: Path) -> sa.Engine:
    engine = sa.create_engine(f"sqlite:///{db_path}")

    @sa.event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _rec) -> None:
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


def _insert_device(conn, device_id: str = "dev1") -> None:
    conn.execute(
        sa.text(
            "INSERT INTO devices (device_id, name, is_tracked, first_seen_at, last_seen_at) "
            "VALUES (:id, 'Tag1', 0, :now, :now)"
        ),
        {"id": device_id, "now": NOW},
    )


def _insert_group(conn, name: str = "Family") -> int:
    conn.execute(
        sa.text("INSERT INTO groups (name, created_at) VALUES (:name, :now)"),
        {"name": name, "now": NOW},
    )
    return conn.execute(
        sa.text("SELECT id FROM groups WHERE name = :name"), {"name": name}
    ).scalar_one()


def test_upgrade_creates_all_tables(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0005")
    inspector = sa.inspect(_engine(db_path))
    names = set(inspector.get_table_names())
    assert names >= _TABLES


def test_groups_name_unique(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0005")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _insert_group(conn, "Family")
    with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            sa.text("INSERT INTO groups (name, created_at) VALUES ('Family', :now)"),
            {"now": NOW},
        )


def test_groups_cluster_radius_check(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0005")
    engine = _engine(db_path)
    with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            sa.text(
                "INSERT INTO groups (name, cluster_radius_meters, created_at) "
                "VALUES ('Bad', 24, :now)"
            ),
            {"now": NOW},
        )
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO groups (name, cluster_radius_meters, created_at) "
                "VALUES ('Good', 25, :now)"
            ),
            {"now": NOW},
        )
        count = conn.execute(
            sa.text("SELECT COUNT(*) FROM groups WHERE name = 'Good'")
        ).scalar_one()
    assert count == 1


def test_alert_rules_xor_check(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0005")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _insert_device(conn)
        group_id = _insert_group(conn)

    with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            sa.text(
                "INSERT INTO alert_rules (name, group_id, device_id, channel, created_at) "
                "VALUES ('R1', :gid, 'dev1', 'telegram', :now)"
            ),
            {"gid": group_id, "now": NOW},
        )
    with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            sa.text(
                "INSERT INTO alert_rules (name, channel, created_at) "
                "VALUES ('R2', 'telegram', :now)"
            ),
            {"now": NOW},
        )
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO alert_rules (name, group_id, channel, created_at) "
                "VALUES ('R3', :gid, 'telegram', :now)"
            ),
            {"gid": group_id, "now": NOW},
        )
        count = conn.execute(
            sa.text("SELECT COUNT(*) FROM alert_rules WHERE name = 'R3'")
        ).scalar_one()
    assert count == 1


def test_alert_rules_channel_check(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0005")
    engine = _engine(db_path)
    with engine.begin() as conn:
        group_id = _insert_group(conn)
    with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            sa.text(
                "INSERT INTO alert_rules (name, group_id, channel, created_at) "
                "VALUES ('R1', :gid, 'sms', :now)"
            ),
            {"gid": group_id, "now": NOW},
        )


def test_alert_deliveries_unique(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0005")
    engine = _engine(db_path)
    with engine.begin() as conn:
        group_id = _insert_group(conn)
        conn.execute(
            sa.text(
                "INSERT INTO alert_rules (name, group_id, channel, created_at) "
                "VALUES ('R1', :gid, 'telegram', :now)"
            ),
            {"gid": group_id, "now": NOW},
        )
        rule_id = conn.execute(sa.text("SELECT id FROM alert_rules")).scalar_one()
        conn.execute(
            sa.text(
                "INSERT INTO alert_deliveries (rule_id, event_kind, event_id, sent_at, status) "
                "VALUES (:rid, 'device', 5, :now, 'sent')"
            ),
            {"rid": rule_id, "now": NOW},
        )
    with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            sa.text(
                "INSERT INTO alert_deliveries (rule_id, event_kind, event_id, sent_at, status) "
                "VALUES (:rid, 'device', 5, :now, 'sent')"
            ),
            {"rid": rule_id, "now": NOW},
        )


def test_cascade_delete_group(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0005")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _insert_device(conn)
        group_id = _insert_group(conn)
        conn.execute(
            sa.text("INSERT INTO device_group (device_id, group_id) VALUES ('dev1', :gid)"),
            {"gid": group_id},
        )
        conn.execute(sa.text("DELETE FROM groups WHERE id = :gid"), {"gid": group_id})
        count = conn.execute(sa.text("SELECT COUNT(*) FROM device_group")).scalar_one()
    assert count == 0


def test_downgrade_removes_tables(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0005")
    command.downgrade(cfg, "0004")
    inspector = sa.inspect(_engine(db_path))
    names = set(inspector.get_table_names())
    assert not (_TABLES & names)
