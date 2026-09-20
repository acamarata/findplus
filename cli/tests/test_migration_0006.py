"""Migration 0006: the uq_gpe_dedup constraint on group_place_events.

Purpose : Prove the constraint fires on an exact duplicate, tolerates a later
          crossing of the same place, survives a downgrade/upgrade round trip,
          and -- the case CF-8 exists for -- that upgrading a database which
          ALREADY holds duplicates succeeds instead of stranding the user at
          0005 with a daemon that will not start.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command

from findplus.db.migrate import get_alembic_config

NOW = "2026-09-19T00:00:00"
LATER = "2026-09-19T06:00:00"


def _cfg(tmp_path: Path):
    db_path = tmp_path / "t.sqlite"
    return get_alembic_config(f"sqlite:///{db_path}"), db_path


def _seed_group_and_place(conn) -> tuple[int, int]:
    conn.execute(
        sa.text("INSERT INTO groups (name, created_at) VALUES ('Family', :now)"), {"now": NOW}
    )
    group_id = conn.execute(sa.text("SELECT id FROM groups")).scalar_one()
    conn.execute(
        sa.text(
            "INSERT INTO places (name, latitude_e7, longitude_e7, radius_meters,"
            " created_at, updated_at) VALUES ('Home', 411000000, -806400000, 100, :now, :now)"
        ),
        {"now": NOW},
    )
    place_id = conn.execute(sa.text("SELECT id FROM places")).scalar_one()
    return group_id, place_id


def _insert_event(conn, group_id: int, place_id: int, observed_at: str = NOW) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO group_place_events (group_id, place_id, event_type, observed_at,"
            " member_event_ids, members_crossed, members_considered, members_stale, confidence)"
            " VALUES (:g, :p, 'ENTER', :at, '[]', 2, 3, 0, 'high')"
        ),
        {"g": group_id, "p": place_id, "at": observed_at},
    )


def _count(engine: sa.Engine) -> int:
    with engine.begin() as conn:
        return conn.execute(sa.text("SELECT COUNT(*) FROM group_place_events")).scalar_one()


def test_upgrade_refuses_an_exact_duplicate(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0006")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        group_id, place_id = _seed_group_and_place(conn)
        _insert_event(conn, group_id, place_id)
    with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
        _insert_event(conn, group_id, place_id)


def test_a_later_crossing_of_the_same_place_is_allowed(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0006")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        group_id, place_id = _seed_group_and_place(conn)
        _insert_event(conn, group_id, place_id, NOW)
        _insert_event(conn, group_id, place_id, LATER)
    assert _count(engine) == 2


def test_upgrade_collapses_duplicates_that_predate_the_constraint(tmp_path: Path) -> None:
    """CF-8's own population: a 1.0 install that already lost the race must upgrade.

    Without the DELETE in upgrade(), create_unique_constraint aborts on
    _alembic_tmp_group_place_events, alembic_version stays at 0005 and
    `findplus start` (which auto-upgrades) never comes up.
    """
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0005")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        group_id, place_id = _seed_group_and_place(conn)
        _insert_event(conn, group_id, place_id, NOW)
        _insert_event(conn, group_id, place_id, NOW)  # the duplicate 0005 permitted
        _insert_event(conn, group_id, place_id, LATER)  # a genuine later crossing
    assert _count(engine) == 3
    survivor = None
    with engine.begin() as conn:
        survivor = conn.execute(
            sa.text("SELECT MIN(id) FROM group_place_events WHERE observed_at = :at"), {"at": NOW}
        ).scalar_one()

    command.upgrade(cfg, "0006")

    with engine.begin() as conn:
        version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
        rows = conn.execute(
            sa.text("SELECT id, observed_at FROM group_place_events ORDER BY id")
        ).all()
    assert version == "0006"
    assert [r.observed_at for r in rows] == [NOW, LATER], "one row per crossing survives"
    assert rows[0].id == survivor, "the earliest duplicate is the one kept"


def test_downgrade_then_upgrade_round_trips(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0006")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        group_id, place_id = _seed_group_and_place(conn)
        _insert_event(conn, group_id, place_id)

    command.downgrade(cfg, "0005")
    with engine.begin() as conn:  # the constraint is gone, so the duplicate lands
        _insert_event(conn, group_id, place_id)
    assert _count(engine) == 2

    command.upgrade(cfg, "0006")
    assert _count(engine) == 1
    with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
        _insert_event(conn, group_id, place_id)
