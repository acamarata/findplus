"""Migration 0009: null out invented Apple Find My accuracy values (CF-P2-6).

Purpose : Prove the upgrade nulls only rows the removed CONFIDENCE_TO_ACCURACY
          heuristic could have written -- source='apple-find-my' AND
          accuracy_meters in the four invented constants -- and leaves every
          other row (a different source, a different accuracy figure, or an
          already-null accuracy) untouched. downgrade() is a documented no-op.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command

from findplus.db.migrate import get_alembic_config

NOW = "2026-09-19T12:00:00"

# The exact constants the removed CONFIDENCE_TO_ACCURACY dict wrote, in
# label order: excellent, good, medium, poor.
_INVENTED = (10.0, 30.0, 65.0, 150.0)


def _cfg(tmp_path: Path):
    db_path = tmp_path / "t.sqlite"
    return get_alembic_config(f"sqlite:///{db_path}"), db_path


def _seed_device(conn, device_id: str) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO devices (device_id, name, is_tracked, first_seen_at, last_seen_at) "
            "VALUES (:id, :id, 1, :now, :now)"
        ),
        {"id": device_id, "now": NOW},
    )


def _seed_observation(
    conn, device_id: str, obs_id: int, source: str | None, accuracy: float | None
) -> None:
    # `obs_id` also offsets observed_at (minutes past NOW) so several rows for
    # the same device never collide with uq_observation_identity.
    conn.execute(
        sa.text(
            "INSERT INTO location_observations (id, device_id, device_name, latitude_e7,"
            " longitude_e7, accuracy_meters, observed_at, first_fetched_at, last_fetched_at,"
            " times_returned, source) VALUES (:id, :dev, :dev, 411000000, -806400000, :acc,"
            " :at, :now, :now, 1, :src)"
        ),
        {
            "id": obs_id,
            "dev": device_id,
            "acc": accuracy,
            "at": f"2026-09-19T12:{obs_id:02d}:00",
            "now": NOW,
            "src": source,
        },
    )


def _accuracy_by_id(engine: sa.Engine) -> dict[int, float | None]:
    with engine.begin() as conn:
        rows = conn.execute(
            sa.text("SELECT id, accuracy_meters FROM location_observations ORDER BY id")
        ).all()
    return {r.id: r.accuracy_meters for r in rows}


def test_upgrade_nulls_only_apple_rows_with_an_invented_value(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0008")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        _seed_device(conn, "apple:abc")
        _seed_device(conn, "goog:xyz")
        # One row per invented constant, all from apple-find-my: must be nulled.
        for i, value in enumerate(_INVENTED, start=1):
            _seed_observation(conn, "apple:abc", i, "apple-find-my", value)
        # A genuinely measured Google accuracy that happens to share no value
        # with the invented set: must survive untouched.
        _seed_observation(conn, "goog:xyz", 10, "crowdsourced", 42.0)
        # A Google row whose accuracy coincidentally equals one of the four
        # invented numbers: source isn't apple-find-my, so it must survive.
        _seed_observation(conn, "goog:xyz", 11, "crowdsourced", 30.0)
        # An Apple row already null (the current, honest behaviour): stays null.
        _seed_observation(conn, "apple:abc", 12, "apple-find-my", None)
        # An Apple row with a value NOT in the invented set (e.g. a future,
        # genuinely-measured source): must survive.
        _seed_observation(conn, "apple:abc", 13, "apple-find-my", 42.0)

    command.upgrade(cfg, "0009")

    accuracy = _accuracy_by_id(engine)
    assert accuracy[1] is None
    assert accuracy[2] is None
    assert accuracy[3] is None
    assert accuracy[4] is None
    assert accuracy[10] == 42.0
    assert accuracy[11] == 30.0
    assert accuracy[12] is None
    assert accuracy[13] == 42.0

    with engine.begin() as conn:
        version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "0009"


def test_upgrade_on_a_db_with_no_apple_rows_is_a_no_op(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0008")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        _seed_device(conn, "goog:xyz")
        _seed_observation(conn, "goog:xyz", 1, "crowdsourced", 30.0)

    command.upgrade(cfg, "0009")
    assert _accuracy_by_id(engine) == {1: 30.0}


def test_downgrade_is_a_documented_no_op_and_does_not_error(tmp_path: Path) -> None:
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "0009")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        _seed_device(conn, "apple:abc")
        _seed_observation(conn, "apple:abc", 1, "apple-find-my", None)

    command.downgrade(cfg, "0008")
    with engine.begin() as conn:
        version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "0008"
    # The null accuracy is unaffected either way; downgrade never re-invents it.
    assert _accuracy_by_id(engine) == {1: None}

    command.upgrade(cfg, "0009")
    assert _accuracy_by_id(engine) == {1: None}


def test_full_head_upgrade_reaches_0009(tmp_path: Path) -> None:
    """The whole chain from scratch still lands on 0009 with no errors."""
    cfg, db_path = _cfg(tmp_path)
    command.upgrade(cfg, "head")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "0009"
