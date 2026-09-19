"""Migration 0004: places, place_events, place_states tables.

Purpose : Prove the schema round-trips, every CHECK constraint fires, and both
          ON DELETE CASCADE paths (place -> children, observation -> place_events)
          actually cascade instead of raising IntegrityError.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command

from findplus.db.migrate import get_alembic_config

NOW = "2026-09-19T00:00:00"


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


def _insert_place(conn, name: str = "Home") -> int:
    conn.execute(
        sa.text(
            "INSERT INTO places (name, latitude_e7, longitude_e7, radius_meters, color, "
            "enter_confirmations, exit_confirmations, created_at, updated_at) "
            "VALUES (:name, 411000000, -806400000, 100, '#2f80ed', 1, 2, :now, :now)"
        ),
        {"name": name, "now": NOW},
    )
    return conn.execute(
        sa.text("SELECT id FROM places WHERE name = :name"), {"name": name}
    ).scalar_one()


def test_upgrade_creates_three_tables(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0004")
    inspector = sa.inspect(_engine(db_path))
    names = inspector.get_table_names()
    assert {"places", "place_events", "place_states"} <= set(names)


def test_downgrade_removes_three_tables(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0004")
    command.downgrade(cfg, "0003")
    inspector = sa.inspect(_engine(db_path))
    names = set(inspector.get_table_names())
    assert not ({"places", "place_events", "place_states"} & names)


def test_check_radius_min(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0004")
    engine = _engine(db_path)
    with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            sa.text(
                "INSERT INTO places (name, latitude_e7, longitude_e7, radius_meters, "
                "created_at, updated_at) VALUES ('P', 0, 0, 19, :now, :now)"
            ),
            {"now": NOW},
        )


def test_check_radius_max(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0004")
    engine = _engine(db_path)
    with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            sa.text(
                "INSERT INTO places (name, latitude_e7, longitude_e7, radius_meters, "
                "created_at, updated_at) VALUES ('P', 0, 0, 5001, :now, :now)"
            ),
            {"now": NOW},
        )


def test_check_event_type(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0004")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _insert_device(conn)
        place_id = _insert_place(conn)
        conn.execute(
            sa.text(
                "INSERT INTO location_observations (device_id, device_name, latitude_e7, "
                "longitude_e7, observed_at, first_fetched_at, last_fetched_at, times_returned) "
                "VALUES ('dev1', 'Tag1', 0, 0, :now, :now, :now, 1)"
            ),
            {"now": NOW},
        )
        obs_id = conn.execute(sa.text("SELECT id FROM location_observations")).scalar_one()
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO place_events (place_id, device_id, event_type, observed_at, "
                    "fetched_at, observation_id, confidence, distance_meters) "
                    "VALUES (:pid, 'dev1', 'PASS', :now, :now, :oid, 'high', 1.0)"
                ),
                {"pid": place_id, "oid": obs_id, "now": NOW},
            )


def test_check_confidence(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0004")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _insert_device(conn)
        place_id = _insert_place(conn)
        conn.execute(
            sa.text(
                "INSERT INTO location_observations (device_id, device_name, latitude_e7, "
                "longitude_e7, observed_at, first_fetched_at, last_fetched_at, times_returned) "
                "VALUES ('dev1', 'Tag1', 0, 0, :now, :now, :now, 1)"
            ),
            {"now": NOW},
        )
        obs_id = conn.execute(sa.text("SELECT id FROM location_observations")).scalar_one()
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO place_events (place_id, device_id, event_type, observed_at, "
                    "fetched_at, observation_id, confidence, distance_meters) "
                    "VALUES (:pid, 'dev1', 'ENTER', :now, :now, :oid, 'extreme', 1.0)"
                ),
                {"pid": place_id, "oid": obs_id, "now": NOW},
            )


def test_check_enter_confirmations(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0004")
    engine = _engine(db_path)
    with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            sa.text(
                "INSERT INTO places (name, latitude_e7, longitude_e7, radius_meters, "
                "enter_confirmations, created_at, updated_at) "
                "VALUES ('P', 0, 0, 100, 0, :now, :now)"
            ),
            {"now": NOW},
        )


def test_check_state(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0004")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _insert_device(conn)
        place_id = _insert_place(conn)
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO place_states (place_id, device_id, state, streak, updated_at) "
                    "VALUES (:pid, 'dev1', 'present', 0, :now)"
                ),
                {"pid": place_id, "now": NOW},
            )


def test_cascade_delete_place(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0004")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _insert_device(conn)
        place_id = _insert_place(conn)
        conn.execute(
            sa.text(
                "INSERT INTO location_observations (device_id, device_name, latitude_e7, "
                "longitude_e7, observed_at, first_fetched_at, last_fetched_at, times_returned) "
                "VALUES ('dev1', 'Tag1', 0, 0, :now, :now, :now, 1)"
            ),
            {"now": NOW},
        )
        obs_id = conn.execute(sa.text("SELECT id FROM location_observations")).scalar_one()
        conn.execute(
            sa.text(
                "INSERT INTO place_events (place_id, device_id, event_type, observed_at, "
                "fetched_at, observation_id, confidence, distance_meters) "
                "VALUES (:pid, 'dev1', 'ENTER', :now, :now, :oid, 'high', 1.0)"
            ),
            {"pid": place_id, "oid": obs_id, "now": NOW},
        )
        conn.execute(
            sa.text(
                "INSERT INTO place_states (place_id, device_id, state, streak, updated_at) "
                "VALUES (:pid, 'dev1', 'inside', 0, :now)"
            ),
            {"pid": place_id, "now": NOW},
        )
        conn.execute(sa.text("DELETE FROM places WHERE id = :pid"), {"pid": place_id})
        events = conn.execute(sa.text("SELECT COUNT(*) FROM place_events")).scalar_one()
        states = conn.execute(sa.text("SELECT COUNT(*) FROM place_states")).scalar_one()
    assert events == 0
    assert states == 0


def test_cascade_delete_observation(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0004")
    engine = _engine(db_path)
    with engine.begin() as conn:
        _insert_device(conn)
        place_id = _insert_place(conn)
        conn.execute(
            sa.text(
                "INSERT INTO location_observations (device_id, device_name, latitude_e7, "
                "longitude_e7, observed_at, first_fetched_at, last_fetched_at, times_returned) "
                "VALUES ('dev1', 'Tag1', 0, 0, :now, :now, :now, 1)"
            ),
            {"now": NOW},
        )
        obs_id = conn.execute(sa.text("SELECT id FROM location_observations")).scalar_one()
        conn.execute(
            sa.text(
                "INSERT INTO place_events (place_id, device_id, event_type, observed_at, "
                "fetched_at, observation_id, confidence, distance_meters) "
                "VALUES (:pid, 'dev1', 'ENTER', :now, :now, :oid, 'high', 1.0)"
            ),
            {"pid": place_id, "oid": obs_id, "now": NOW},
        )
        conn.execute(sa.text("DELETE FROM location_observations WHERE id = :oid"), {"oid": obs_id})
        events = conn.execute(sa.text("SELECT COUNT(*) FROM place_events")).scalar_one()
    assert events == 0
