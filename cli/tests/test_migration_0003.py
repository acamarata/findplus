"""Migration 0003: devices.provider column, backfilled with a server_default."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command

from findplus.db.migrate import get_alembic_config


def _cfg(tmp_path: Path):
    db_path = tmp_path / "t.sqlite"
    return get_alembic_config(f"sqlite:///{db_path}"), db_path


def test_upgrade_adds_provider(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0003")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO devices (device_id, name, is_tracked, first_seen_at, "
                "last_seen_at) VALUES (:id, :name, 0, '2026-09-19T00:00:00', "
                "'2026-09-19T00:00:00')"
            ),
            {"id": "TAG-001", "name": "Moto Tag 2"},
        )
        conn.execute(
            sa.text(
                "INSERT INTO devices (device_id, name, is_tracked, first_seen_at, "
                "last_seen_at) VALUES (:id, :name, 0, '2026-09-19T00:00:00', "
                "'2026-09-19T00:00:00')"
            ),
            {"id": "TAG-002", "name": "Moto Tag 3"},
        )
        rows = conn.execute(sa.text("SELECT provider FROM devices ORDER BY device_id")).all()

    assert [r[0] for r in rows] == ["google-find-hub", "google-find-hub"]


def test_downgrade_removes_provider(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0003")
    command.downgrade(cfg, "0002")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        columns = conn.execute(sa.text("PRAGMA table_info(devices)")).all()

    column_names = {row[1] for row in columns}
    assert "provider" not in column_names


def test_new_device_default(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0003")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO devices (device_id, name, is_tracked, first_seen_at, "
                "last_seen_at) VALUES (:id, :name, 0, '2026-09-19T00:00:00', "
                "'2026-09-19T00:00:00')"
            ),
            {"id": "TAG-003", "name": "Moto Tag 4"},
        )
        provider = conn.execute(
            sa.text("SELECT provider FROM devices WHERE device_id = :id"), {"id": "TAG-003"}
        ).scalar_one()

    assert provider == "google-find-hub"


def test_upgrade_backfills_rows_that_existed_at_0002(tmp_path: Path) -> None:
    """The real upgrade case: rows already on record before the column existed."""
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0002")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO devices (device_id, name, is_tracked, first_seen_at, "
                "last_seen_at) VALUES ('PRE-001', 'Older tag', 1, "
                "'2026-01-01T00:00:00', '2026-01-01T00:00:00')"
            )
        )

    command.upgrade(cfg, "0003")

    with engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT provider, is_tracked FROM devices WHERE device_id = 'PRE-001'")
        ).one()
        columns = {r[1]: r for r in conn.execute(sa.text("PRAGMA table_info(devices)")).all()}
        indexes = {r[1] for r in conn.execute(sa.text("PRAGMA index_list(devices)")).all()}

    assert row[0] == "google-find-hub", "existing rows are backfilled, not left NULL"
    assert row[1] == 1, "the batch table rebuild preserves the other columns"
    assert columns["provider"][3] == 1, "NOT NULL (data-model.md § devices)"
    assert columns["provider"][4] == "'google-find-hub'", "server_default, not a Python default"
    assert "ix_devices_provider" in indexes
    assert "ix_devices_tracked" in indexes, "the pre-existing index survives the rebuild"


def test_downgrade_then_upgrade_round_trips(tmp_path: Path) -> None:
    """0003 is reversible and re-appliable; the index goes with the column."""
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0003")
    command.downgrade(cfg, "0002")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        assert "ix_devices_provider" not in {
            r[1] for r in conn.execute(sa.text("PRAGMA index_list(devices)")).all()
        }

    command.upgrade(cfg, "0003")
    with engine.connect() as conn:
        assert "ix_devices_provider" in {
            r[1] for r in conn.execute(sa.text("PRAGMA index_list(devices)")).all()
        }
