"""Migration 0007/0008 must not lose cascading rows on a real 1.0.x database.

Purpose : Regression coverage for CF-P2-15 and CR-C-E8 F3. Alembic's SQLite batch mode
    rebuilds an altered table by creating a new one, copying rows in, then
    dropping the original -- and that DROP runs an implicit DELETE while
    findplus.db.session's `PRAGMA foreign_keys=ON` is enforced, which fires
    every ON DELETE CASCADE on the table being altered. `devices` and
    `groups` are both parents of CASCADE children (device_group, alert_rules,
    group_place_events), so an unguarded rebuild of either one silently
    destroys those rows on any database that already has data -- exactly the
    shape of a 1.0.x install upgrading to 1.1. This seeds a revision-0006
    database (the last revision before P2) with one row in every table that
    sits anywhere in that cascade chain, upgrades to head, and asserts every
    row and the identifying device/group fields survive -- then downgrades
    back to 0006 and asserts the same, since the downgrade path is the one
    that was actually proven (by trace) to trigger the table rebuild today.
    Also proves 0008's downgrade round-trips a live 1.1 database: `queued`/
    `delivered` statuses and multi-channel per-event deliveries (both only
    possible after 0008's own upgrade) don't fit 0007's narrower CHECK/UNIQUE,
    which previously aborted `downgrade 0006` outright (CR-C-E8 F3).
Inputs  : pytest tmp_path fixture only; no real ~/.findplus, no network.
Outputs : none (assertions only).
Constraints: revision 0006 is the fixed pre-P2 shape; never renumber it here.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command

from findplus.db.migrate import fk_disabled, get_alembic_config, upgrade_to_head
from findplus.db.session import get_engine

NOW = "2026-09-20T00:00:00"

# One row per table anywhere in the devices/groups cascade chain, in the
# pre-0007 (revision 0006) column shape.
_TABLES = (
    "devices",
    "location_observations",
    "places",
    "place_events",
    "place_states",
    "groups",
    "device_group",
    "group_place_events",
    "alert_rules",
    "alert_deliveries",
)


def _cfg_and_url(tmp_path: Path):
    db_path = tmp_path / "t.sqlite"
    url = f"sqlite:///{db_path}"
    return get_alembic_config(url), url, db_path


def _engine(url: str) -> sa.Engine:
    engine = sa.create_engine(url)

    @sa.event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _rec) -> None:
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


def _seed_devices_and_observation(conn: sa.Connection) -> None:
    for device_id, name in (("dev1", "Moto Tag 1"), ("dev2", "Moto Tag 2")):
        conn.execute(
            sa.text(
                "INSERT INTO devices (device_id, name, is_tracked, first_seen_at, last_seen_at) "
                "VALUES (:id, :name, 1, :now, :now)"
            ),
            {"id": device_id, "name": name, "now": NOW},
        )
    conn.execute(
        sa.text(
            "INSERT INTO location_observations (device_id, device_name, latitude_e7, "
            "longitude_e7, observed_at, first_fetched_at, last_fetched_at) "
            "VALUES ('dev1', 'Moto Tag 1', 100, 100, :now, :now, :now)"
        ),
        {"now": NOW},
    )


def _seed_place_and_events(conn: sa.Connection) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO places (id, name, latitude_e7, longitude_e7, radius_meters, "
            "created_at, updated_at) VALUES (1, 'Home', 100, 100, 50, :now, :now)"
        ),
        {"now": NOW},
    )
    conn.execute(
        sa.text(
            "INSERT INTO place_events (place_id, device_id, event_type, observed_at, "
            "fetched_at, observation_id, confidence, distance_meters) "
            "VALUES (1, 'dev1', 'ENTER', :now, :now, 1, 'high', 10.0)"
        ),
        {"now": NOW},
    )
    conn.execute(
        sa.text(
            "INSERT INTO place_states (place_id, device_id, state, updated_at) "
            "VALUES (1, 'dev1', 'inside', :now)"
        ),
        {"now": NOW},
    )


def _seed_group_and_alerts(conn: sa.Connection) -> None:
    conn.execute(
        sa.text("INSERT INTO groups (id, name, created_at) VALUES (1, 'Family', :now)"),
        {"now": NOW},
    )
    for device_id in ("dev1", "dev2"):
        conn.execute(
            sa.text("INSERT INTO device_group (device_id, group_id) VALUES (:id, 1)"),
            {"id": device_id},
        )
    conn.execute(
        sa.text(
            "INSERT INTO group_place_events (group_id, place_id, event_type, observed_at, "
            "member_event_ids, members_crossed, members_considered, members_stale, confidence) "
            "VALUES (1, 1, 'ENTER', :now, '1', 1, 2, 0, 'high')"
        ),
        {"now": NOW},
    )
    conn.execute(
        sa.text(
            "INSERT INTO alert_rules (id, name, device_id, on_enter, on_exit, channel, "
            "cooldown_minutes, enabled, also_notify_members, created_at) "
            "VALUES (1, 'device rule', 'dev1', 1, 1, 'telegram', 30, 1, 0, :now)"
        ),
        {"now": NOW},
    )
    conn.execute(
        sa.text(
            "INSERT INTO alert_rules (id, name, group_id, on_enter, on_exit, channel, "
            "cooldown_minutes, enabled, also_notify_members, created_at) "
            "VALUES (2, 'group rule', 1, 1, 1, 'webhook', 30, 1, 0, :now)"
        ),
        {"now": NOW},
    )
    for rule_id, event_id in ((1, 10), (2, 20)):
        conn.execute(
            sa.text(
                "INSERT INTO alert_deliveries (rule_id, event_kind, event_id, sent_at, status) "
                "VALUES (:rid, 'device', :eid, :now, 'sent')"
            ),
            {"rid": rule_id, "eid": event_id, "now": NOW},
        )


def _seed_1_0_x_database(conn: sa.Connection) -> None:
    """Two devices, a place, a group, and one row per cascading child table."""
    _seed_devices_and_observation(conn)
    _seed_place_and_events(conn)
    _seed_group_and_alerts(conn)


def _counts(conn: sa.Connection) -> dict[str, int]:
    return {t: conn.execute(sa.text(f"SELECT COUNT(*) FROM {t}")).scalar_one() for t in _TABLES}


def _device_names(conn: sa.Connection) -> dict[str, str]:
    return dict(conn.execute(sa.text("SELECT device_id, name FROM devices")).all())


def test_upgrade_to_head_keeps_every_cascading_row(tmp_path: Path) -> None:
    cfg, url, _db_path = _cfg_and_url(tmp_path)
    command.upgrade(cfg, "0006")
    engine = _engine(url)
    with engine.begin() as conn:
        _seed_1_0_x_database(conn)
    with engine.begin() as conn:
        before_counts = _counts(conn)
        before_names = _device_names(conn)

    upgrade_to_head(url)

    engine2 = _engine(url)
    with engine2.begin() as conn:
        after_counts = _counts(conn)
        after_names = _device_names(conn)
    assert after_counts == before_counts
    assert after_names == before_names


def test_downgrade_to_0006_keeps_every_cascading_row(tmp_path: Path) -> None:
    """The downgrade path is the one proven (by SQL trace) to rebuild devices/groups."""
    cfg, url, _db_path = _cfg_and_url(tmp_path)
    command.upgrade(cfg, "0006")
    engine = _engine(url)
    with engine.begin() as conn:
        _seed_1_0_x_database(conn)
    with engine.begin() as conn:
        before_counts = _counts(conn)
        before_names = _device_names(conn)

    upgrade_to_head(url)
    command.downgrade(cfg, "0006")

    engine2 = _engine(url)
    with engine2.begin() as conn:
        after_counts = _counts(conn)
        after_names = _device_names(conn)
    assert after_counts == before_counts
    assert after_names == before_names


def test_fk_disabled_actually_toggles_the_pragma_off_then_on(tmp_path: Path) -> None:
    """Direct proof for CF-P2-15's runner-level guard, not just its side effect.

    Uses findplus.db.session.get_engine (not a bare sa.create_engine) because
    that is the engine every migration actually runs on, and its connect
    listener turns PRAGMA foreign_keys ON for every new connection -- exactly
    the state fk_disabled must turn off before a migration, and must restore
    after.
    """
    get_engine.cache_clear()
    url = f"sqlite:///{tmp_path / 'fk.sqlite'}"
    engine = get_engine(url)
    with engine.connect() as connection:
        dbapi_conn = connection.connection.dbapi_connection
        assert dbapi_conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with fk_disabled(connection):
            assert dbapi_conn.execute("PRAGMA foreign_keys").fetchone()[0] == 0
        assert dbapi_conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    get_engine.cache_clear()


def _seed_mixed_channel_deliveries(conn: sa.Connection) -> None:
    """Three deliveries for the same (rule, event_kind, event_id): the
    narrowed 0007 UNIQUE has no channel column, so these collide unless
    downgrade dedupes first. Statuses cover both of 0008's new states."""
    deliveries = (("telegram", "sent"), ("native", "queued"), ("whatsapp", "delivered"))
    for channel, status in deliveries:
        conn.execute(
            sa.text(
                "INSERT INTO alert_deliveries "
                "(rule_id, event_kind, event_id, channel, sent_at, status) "
                "VALUES (1, 'device', 99, :ch, :now, :st)"
            ),
            {"ch": channel, "now": NOW, "st": status},
        )


def test_downgrade_then_upgrade_round_trips_a_live_1_1_database(tmp_path: Path) -> None:
    """CR-C-E8 F3: downgrade 0006 must survive queued/delivered + multi-channel rows.

    These shapes only exist after 0008's own upgrade (queued/delivered are
    native's states; per-channel rows need the channel column), so they are
    seeded post-upgrade, not as part of the revision-0006 base data.
    """
    cfg, url, _db_path = _cfg_and_url(tmp_path)
    command.upgrade(cfg, "0006")
    engine = _engine(url)
    with engine.begin() as conn:
        _seed_1_0_x_database(conn)

    upgrade_to_head(url)

    engine2 = _engine(url)
    with engine2.begin() as conn:
        _seed_mixed_channel_deliveries(conn)

    # Must not raise: this is exactly the constraint mismatch CR-C-E8 F3 found.
    command.downgrade(cfg, "0006")

    engine3 = _engine(url)
    with engine3.begin() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT rule_id, event_kind, event_id, status FROM alert_deliveries "
                "WHERE rule_id = 1 AND event_id = 99"
            )
        ).all()
    # The narrowed UNIQUE allows exactly one row per (rule, kind, event); the
    # remap left it a status 0007's CHECK actually accepts.
    assert len(rows) == 1
    assert rows[0].status in ("sent", "failed", "skipped")

    # Must also not raise, proving the round trip -- not just the one-way drop.
    command.upgrade(cfg, "0008")
    engine4 = _engine(url)
    with engine4.begin() as conn:
        after = conn.execute(
            sa.text(
                "SELECT channel, status FROM alert_deliveries WHERE rule_id = 1 AND event_id = 99"
            )
        ).all()
    assert len(after) == 1
