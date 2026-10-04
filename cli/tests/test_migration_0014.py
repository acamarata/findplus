"""Migration 0014: the two derived-state markers keep every row and backfill sensibly.

Purpose : observation_quality.fed_at and person_place_states.confirmed_at are
          plain nullable adds; this proves the backfill, the nulls and the
          downgrade, on a database that already holds derived rows.
Inputs  : tmp_path only; no real ~/.findplus, no network.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command

from tests import migration_0013_seed as seed

T0 = "2026-09-21 08:00:00.000000"
T1 = "2026-09-21 09:00:00.000000"


def _cols(engine: sa.Engine, table: str) -> set[str]:
    with engine.connect() as conn:
        return {c["name"] for c in sa.inspect(conn).get_columns(table)}


def _run(conn, sql: str, **params) -> None:
    conn.execute(sa.text(sql), params)


def _seed_0013(engine: sa.Engine) -> None:
    with engine.begin() as conn:
        _run(conn, "INSERT INTO devices (device_id, provider, name, first_seen_at, last_seen_at)"
                   " VALUES ('d1', 'p', 'D', :t, :t)", t=T0)  # fmt: skip
        _run(conn, "INSERT INTO location_observations (id, device_id, latitude_e7, longitude_e7,"
                   " observed_at, first_fetched_at, last_fetched_at, device_name)"
                   " VALUES (1, 'd1', 1, 1, :t, :t, :t, 'D'),"
                   " (2, 'd1', 2, 2, :t, :t, :t, 'D')", t=T0)  # fmt: skip
        _run(conn, "INSERT INTO observation_quality (observation_id, score, suspect, reasons,"
                   " algo_version, computed_at) VALUES (1, 1.0, 0, '', 1, :t),"
                   " (2, 0.1, 1, 'x', 1, :t)", t=T1)  # fmt: skip
        _run(conn, "INSERT INTO groups (id, name, kind, created_at)"
                   " VALUES (1, 'Sam', 'person', :t)", t=T0)  # fmt: skip
        _run(conn, "INSERT INTO places (id, name, latitude_e7, longitude_e7, radius_meters,"
                   " created_at, updated_at) VALUES (1, 'A', 1, 1, 100, :t, :t),"
                   " (2, 'B', 1, 1, 100, :t, :t)",
             t=T0)  # fmt: skip
        _run(conn, "INSERT INTO person_place_states (group_id, place_id, state, since_observed_at,"
                   " updated_at) VALUES (1, 1, 'inside', :a, :b), (1, 2, 'unknown', NULL, :b)",
             a=T0, b=T1)  # fmt: skip


def test_backfill_and_downgrade(tmp_path: Path) -> None:
    cfg, _url, engine = seed.setup(tmp_path, "0013")
    _seed_0013(engine)
    command.upgrade(cfg, "0014")
    assert "fed_at" in _cols(engine, "observation_quality")
    with engine.connect() as conn:
        fed = dict(
            conn.execute(sa.text("SELECT observation_id, fed_at FROM observation_quality")).all()
        )
        seen = dict(
            conn.execute(sa.text("SELECT place_id, confirmed_at FROM person_place_states")).all()
        )
    assert fed[1] is not None and fed[2] is None  # a suspect fix was never fed
    assert seen[1] is not None and seen[2] is None  # an unknown state confirms nothing
    command.downgrade(cfg, "0013")
    assert "fed_at" not in _cols(engine, "observation_quality")
    assert "confirmed_at" not in _cols(engine, "person_place_states")
    assert seed.health(engine) == ([], "ok")
