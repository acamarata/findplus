"""Seed data and helpers for the migration 0013 tests (not a test module).

Purpose : Build a realistic revision-0012 database (three trackers, sightings,
          two places with events and states, two groups with members and a
          group event, device and group rules, a multi-channel, multi-target
          delivery log) and give the tests one place to count and dump it.
Inputs  : a tmp_path; never the real ~/.findplus, never the network.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command

from findplus.db.migrate import get_alembic_config

NOW = "2026-09-30T08:00:00"
OLD_TABLES = (
    "devices",
    "location_observations",
    "poll_runs",
    "places",
    "place_events",
    "place_states",
    "groups",
    "device_group",
    "group_place_events",
    "alert_rules",
    "alert_deliveries",
)
NEW_TABLES = ("person_place_states", "left_behind", "observation_quality", "digest_runs")
_DEVICES = (("d1", "Sam Shoes Red"), ("d2", "Sam Bag"), ("d3", "Ali Phone"))
_DELIVERIES = (
    (1, "device", 1, "telegram", "111", "sent"),
    (1, "device", 1, "telegram", "-100222", "retrying"),
    (1, "device", 2, "native", "", "delivered"),
    (2, "group", 1, "webhook", "", "failed"),
    (2, "group", 1, "whatsapp", "", "queued"),
    (3, "device", 2, "telegram", "111", "skipped"),
)


def setup(tmp_path: Path, revision: str = "0012"):
    """Return (alembic config, url, engine with FKs enforced) at `revision`."""
    url = f"sqlite:///{tmp_path / 't.sqlite'}"
    cfg = get_alembic_config(url)
    command.upgrade(cfg, revision)
    return cfg, url, fk_engine(url)


def fk_engine(url: str) -> sa.Engine:
    engine = sa.create_engine(url)

    @sa.event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _rec) -> None:
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


def _run(conn: sa.Connection, sql: str, rows: list[dict]) -> None:
    for row in rows:
        conn.execute(sa.text(sql), {"now": NOW, **row})


def _seed_devices(conn: sa.Connection) -> None:
    _run(
        conn,
        "INSERT INTO devices (device_id, name, is_tracked, first_seen_at, last_seen_at) "
        "VALUES (:id, :name, 1, :now, :now)",
        [{"id": d, "name": n} for d, n in _DEVICES],
    )
    obs = [{"id": i, "dev": _DEVICES[i % 3][0], "lat": 515000000 + i} for i in range(1, 10)]
    _run(
        conn,
        "INSERT INTO location_observations (id, device_id, device_name, latitude_e7, "
        "longitude_e7, accuracy_meters, observed_at, first_fetched_at, last_fetched_at) "
        "VALUES (:id, :dev, 'n', :lat, -1000000, 30.0, :now, :now, :now)",
        obs,
    )
    _run(
        conn,
        "INSERT INTO poll_runs (device_id, started_at, status) VALUES ('d1', :now, 'ok')",
        [{}],
    )


def _seed_places(conn: sa.Connection) -> None:
    _run(
        conn,
        "INSERT INTO places (id, name, latitude_e7, longitude_e7, radius_meters, "
        "created_at, updated_at) VALUES (:id, :name, 515000000, -1000000, 100, :now, :now)",
        [{"id": 1, "name": "Home"}, {"id": 2, "name": "School"}],
    )
    _run(
        conn,
        "INSERT INTO place_events (place_id, device_id, event_type, observed_at, fetched_at, "
        "observation_id, confidence, distance_meters) "
        "VALUES (:p, :d, 'ENTER', :now, :now, :o, 'high', 12.0)",
        [{"p": 1, "d": "d1", "o": 3}, {"p": 2, "d": "d2", "o": 1}],
    )
    _run(
        conn,
        "INSERT INTO place_states (place_id, device_id, state, updated_at) "
        "VALUES (:p, :d, 'inside', :now)",
        [{"p": 1, "d": "d1"}, {"p": 2, "d": "d2"}],
    )


def _seed_groups(conn: sa.Connection) -> None:
    _run(
        conn,
        "INSERT INTO groups (id, name, created_at) VALUES (:id, :name, :now)",
        [{"id": 1, "name": "Sam"}, {"id": 2, "name": "Family"}],
    )
    _run(
        conn,
        "INSERT INTO device_group (device_id, group_id) VALUES (:d, :g)",
        [{"d": "d1", "g": 1}, {"d": "d2", "g": 1}, {"d": "d1", "g": 2}, {"d": "d3", "g": 2}],
    )
    _run(
        conn,
        "INSERT INTO group_place_events (group_id, place_id, event_type, observed_at, "
        "member_event_ids, members_crossed, members_considered, members_stale, confidence) "
        "VALUES (1, 1, 'ENTER', :now, '[1]', 1, 2, 0, 'high')",
        [{}],
    )


def _seed_alerts(conn: sa.Connection) -> None:
    rule = (
        "INSERT INTO alert_rules (id, name, place_id, {col}, on_enter, on_exit, channels, "
        "cooldown_minutes, enabled, also_notify_members, telegram_targets, created_at) "
        "VALUES (:id, :name, 1, :t, 1, 1, :ch, 30, 1, 0, :tt, :now)"
    )
    _run(
        conn,
        rule.format(col="device_id"),
        [
            {"id": 1, "name": "shoes", "t": "d1", "ch": "native,telegram", "tt": "111,-100222"},
            {"id": 3, "name": "phone", "t": "d3", "ch": "telegram", "tt": None},
        ],
    )
    _run(
        conn,
        rule.format(col="group_id"),
        [{"id": 2, "name": "family", "t": 2, "ch": "webhook,whatsapp", "tt": ""}],
    )
    _run(
        conn,
        "INSERT INTO alert_deliveries (rule_id, event_kind, event_id, channel, target, "
        "sent_at, status, attempts) VALUES (:r, :k, :e, :c, :t, :now, :s, 2)",
        [dict(zip("rkects", d, strict=True)) for d in _DELIVERIES],
    )


def seed_0012(engine: sa.Engine) -> None:
    with engine.begin() as conn:
        _seed_devices(conn)
        _seed_places(conn)
        _seed_groups(conn)
        _seed_alerts(conn)


def counts(engine: sa.Engine, tables: tuple[str, ...] = OLD_TABLES) -> dict[str, int]:
    with engine.connect() as conn:
        return {t: conn.execute(sa.text(f"SELECT COUNT(*) FROM {t}")).scalar_one() for t in tables}


def dump(engine: sa.Engine, table: str, columns: str) -> list[tuple]:
    with engine.connect() as conn:
        return [
            tuple(r) for r in conn.execute(sa.text(f"SELECT {columns} FROM {table} ORDER BY 1"))
        ]


def health(engine: sa.Engine) -> tuple[list, str]:
    """(PRAGMA foreign_key_check rows, PRAGMA integrity_check result)."""
    with engine.connect() as conn:
        fk = list(conn.exec_driver_sql("PRAGMA foreign_key_check").all())
        ok = conn.exec_driver_sql("PRAGMA integrity_check").scalar_one()
    return fk, ok


def revision(engine: sa.Engine) -> str:
    with engine.connect() as conn:
        return conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()


RULE_COLS = (
    "id, name, place_id, group_id, device_id, on_enter, on_exit, channels, "
    "cooldown_minutes, enabled, also_notify_members, telegram_targets, created_at"
)
DELIVERY_COLS = (
    "id, rule_id, event_kind, event_id, sent_at, status, error, channel, target, "
    "delivered_at, attempts, next_attempt_at"
)
