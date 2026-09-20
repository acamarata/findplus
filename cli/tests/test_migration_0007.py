"""Migration 0007: devices.label/icon/color and groups.icon.

Purpose : Prove the new columns arrive with the defaults the spec pins, that
          every device that predates the revision is backfilled a palette
          colour, and that the downgrade path is clean.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import sqlalchemy as sa
from alembic import command

from findplus.db.migrate import get_alembic_config

NOW = "2026-09-20T00:00:00"

_DEVICE_COLUMNS = {"label", "icon", "color"}

# A deliberate third copy of the formula: this test is what stops migration
# 0007 and findplus/labels.py drifting apart, so it must not import either.
_PALETTE = [
    "#4f8cf7",
    "#e7663f",
    "#37c67a",
    "#c77ae6",
    "#e7b53f",
    "#3fc9d6",
    "#e64f7a",
    "#8fb43f",
    "#f2994a",
    "#9b6bd6",
    "#4fd6a8",
    "#d65f5f",
]


def _expected_color(device_id: str) -> str:
    return _PALETTE[int(hashlib.sha1(device_id.encode("utf-8")).hexdigest(), 16) % 12]


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


def _columns(db_path: Path, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(_engine(db_path)).get_columns(table)}


def test_upgrade_adds_the_label_columns(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0007")
    assert _columns(db_path, "devices") >= _DEVICE_COLUMNS
    assert "icon" in _columns(db_path, "groups")


def test_new_device_row_defaults_to_the_letter_icon(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0007")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _insert_device(conn, "after")
    with engine.begin() as conn:
        row = conn.execute(
            sa.text("SELECT label, icon, color FROM devices WHERE device_id = 'after'")
        ).one()
    assert row.label is None
    assert row.icon == "letter"
    assert row.color == "#888888"


def test_existing_devices_are_backfilled_a_palette_color(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0006")
    engine = _engine(db_path)
    seeded = ["TAG-001", "phone-7", "b0b0b0"]
    with engine.begin() as conn:
        for device_id in seeded:
            _insert_device(conn, device_id)
    command.upgrade(cfg, "0007")
    with engine.begin() as conn:
        colors = dict(conn.execute(sa.text("SELECT device_id, color FROM devices")).all())
    assert colors == {device_id: _expected_color(device_id) for device_id in seeded}


def test_new_group_row_defaults_to_the_users_icon(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0007")
    engine = _engine(db_path)
    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO groups (name, created_at) VALUES ('Family', :now)"),
            {"now": NOW},
        )
    with engine.begin() as conn:
        icon = conn.execute(sa.text("SELECT icon FROM groups WHERE name = 'Family'")).scalar_one()
    assert icon == "lucide:users"


def test_downgrade_removes_every_column_it_added(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0007")
    command.downgrade(cfg, "0006")
    assert not (_DEVICE_COLUMNS & _columns(db_path, "devices"))
    assert "icon" not in _columns(db_path, "groups")
