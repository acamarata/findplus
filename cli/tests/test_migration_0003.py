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
