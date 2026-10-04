"""Migration 0013: people and quality schema keeps every 0012 row and every cascade.

Purpose : The two batch rebuilds (alert_deliveries, alert_rules) are the risk:
          alert_deliveries.rule_id is ON DELETE CASCADE, so a rebuild with
          foreign keys on wipes the delivery log. These tests seed a realistic
          0012 database, upgrade, and prove zero row loss, unchanged rule and
          delivery content, clean foreign_key_check and integrity_check, the
          new defaults, and that every cascade still fires afterwards.
Inputs  : tmp_path only; no real ~/.findplus, no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa

from findplus.db.migrate import upgrade_to_head
from findplus.db.session import get_engine
from tests import migration_0013_seed as seed


@pytest.fixture
def upgraded(tmp_path: Path):
    """A seeded 0012 database upgraded to head, plus its pre-upgrade snapshot."""
    _cfg, url, engine = seed.setup(tmp_path)
    seed.seed_0012(engine)
    before = {
        "counts": seed.counts(engine),
        "rules": seed.dump(engine, "alert_rules", seed.RULE_COLS),
        "deliveries": seed.dump(engine, "alert_deliveries", seed.DELIVERY_COLS),
    }
    get_engine.cache_clear()
    upgrade_to_head(url)
    get_engine.cache_clear()
    return seed.fk_engine(url), before


def _exec(engine: sa.Engine, sql: str, **params) -> None:
    with engine.begin() as conn:
        conn.execute(sa.text(sql), {"now": seed.NOW, **params})


def _scalar(engine: sa.Engine, sql: str):
    with engine.connect() as conn:
        return conn.execute(sa.text(sql)).scalar()


def test_upgrade_reaches_head_with_zero_row_loss(upgraded) -> None:
    engine, before = upgraded
    assert seed.revision(engine) == "0014"
    assert seed.counts(engine) == before["counts"]
    assert seed.counts(engine, seed.NEW_TABLES) == dict.fromkeys(seed.NEW_TABLES, 0)


def test_rules_and_delivery_log_survive_byte_for_byte(upgraded) -> None:
    engine, before = upgraded
    assert seed.dump(engine, "alert_rules", seed.RULE_COLS) == before["rules"]
    assert seed.dump(engine, "alert_deliveries", seed.DELIVERY_COLS) == before["deliveries"]
    assert len(before["deliveries"]) == 6


def test_foreign_key_and_integrity_checks_are_clean(upgraded) -> None:
    engine, _ = upgraded
    assert seed.health(engine) == ([], "ok")


def test_new_columns_default_to_todays_behaviour(upgraded) -> None:
    engine, _ = upgraded
    assert _scalar(engine, "SELECT group_concat(DISTINCT kind) FROM groups") == "set"
    assert _scalar(engine, "SELECT COUNT(*) FROM devices WHERE role IS NOT NULL") == 0
    assert _scalar(engine, "SELECT COUNT(*) FROM devices WHERE carry_weight IS NOT NULL") == 0
    assert _scalar(engine, "SELECT basis FROM group_place_events") == "quorum"
    assert _scalar(engine, "SELECT note IS NULL AND lead_device_id IS NULL FROM group_place_events")
    assert _scalar(engine, "SELECT SUM(all_people) FROM alert_rules") == 0


def test_existing_places_get_a_kind_guess_marked_for_confirmation(upgraded) -> None:
    """An upgrade must not leave "Home" as kind other (left-behind alerts on at
    Home, no "Overnight at Home"): the name's guess is stored and flagged so
    the places list asks the owner to confirm it (review r116 #8)."""
    engine, _ = upgraded
    rows = seed.dump(engine, "places", "name, kind, kind_guessed")
    assert rows == [("Home", "home", 1), ("School", "school", 1)]


def test_rule_delete_still_cascades_to_its_deliveries(upgraded) -> None:
    engine, _ = upgraded
    _exec(engine, "DELETE FROM alert_rules WHERE id = 1")
    assert _scalar(engine, "SELECT COUNT(*) FROM alert_deliveries WHERE rule_id = 1") == 0
    assert _scalar(engine, "SELECT COUNT(*) FROM alert_deliveries") == 3


def test_group_place_and_device_cascades_reach_the_rebuilt_rules(upgraded) -> None:
    engine, _ = upgraded
    _exec(engine, "DELETE FROM groups WHERE id = 2")
    assert _scalar(engine, "SELECT COUNT(*) FROM alert_rules WHERE id = 2") == 0
    assert _scalar(engine, "SELECT COUNT(*) FROM alert_deliveries WHERE rule_id = 2") == 0
    _exec(engine, "DELETE FROM places WHERE id = 1")
    assert _scalar(engine, "SELECT COUNT(*) FROM alert_rules") == 0
    assert _scalar(engine, "SELECT COUNT(*) FROM alert_deliveries") == 0
    assert seed.health(engine) == ([], "ok")


def _fill_new_tables(engine: sa.Engine) -> None:
    _exec(
        engine,
        "INSERT INTO person_place_states (group_id, place_id, state, updated_at) "
        "VALUES (1, 2, 'inside', :now)",
    )
    _exec(
        engine,
        "INSERT INTO left_behind (group_id, device_id, place_id, anchor_lat_e7, anchor_lon_e7, "
        "state, started_observed_at) VALUES (1, 'd2', 2, 515000000, -1000000, 'left_behind', :now)",
    )
    _exec(
        engine,
        "INSERT INTO observation_quality (observation_id, score, suspect, reasons, "
        "corroborated_by, algo_version, computed_at) "
        "VALUES (4, 0.2, 1, 'aba_teleport', 5, 1, :now)",
    )
    _exec(
        engine,
        "INSERT INTO digest_runs (group_id, local_date, channel, target, status, sent_at) "
        "VALUES (1, '2026-09-30', 'telegram', '111', 'sent', :now)",
    )


def test_new_tables_cascade_from_their_parents(upgraded) -> None:
    engine, _ = upgraded
    _fill_new_tables(engine)
    _exec(engine, "DELETE FROM places WHERE id = 2")
    assert _scalar(engine, "SELECT COUNT(*) FROM person_place_states") == 0
    assert _scalar(engine, "SELECT place_id FROM left_behind") is None  # SET NULL, row kept
    _exec(engine, "DELETE FROM location_observations WHERE id = 5")
    assert _scalar(engine, "SELECT corroborated_by FROM observation_quality") is None
    _exec(engine, "DELETE FROM location_observations WHERE id = 4")
    assert _scalar(engine, "SELECT COUNT(*) FROM observation_quality") == 0
    _exec(engine, "DELETE FROM groups WHERE id = 1")
    assert _scalar(engine, "SELECT COUNT(*) FROM left_behind") == 0
    assert _scalar(engine, "SELECT COUNT(*) FROM digest_runs") == 0
    assert seed.health(engine) == ([], "ok")


def test_left_behind_cascades_from_its_device(upgraded) -> None:
    engine, _ = upgraded
    _fill_new_tables(engine)
    _exec(engine, "DELETE FROM device_group WHERE device_id = 'd2'")
    _exec(engine, "DELETE FROM place_states WHERE device_id = 'd2'")
    _exec(engine, "DELETE FROM place_events WHERE device_id = 'd2'")
    _exec(engine, "DELETE FROM location_observations WHERE device_id = 'd2'")
    _exec(engine, "DELETE FROM devices WHERE device_id = 'd2'")
    assert _scalar(engine, "SELECT COUNT(*) FROM left_behind") == 0


def test_digest_runs_never_records_the_same_send_twice(upgraded) -> None:
    engine, _ = upgraded
    _fill_new_tables(engine)
    with pytest.raises(sa.exc.IntegrityError):
        _exec(
            engine,
            "INSERT INTO digest_runs (group_id, local_date, channel, target, status) "
            "VALUES (1, '2026-09-30', 'telegram', '111', 'failed')",
        )


@pytest.mark.parametrize(
    ("all_people", "group_id", "device_id", "ok"),
    [
        (1, None, None, True),
        (1, 1, None, False),
        (1, None, "d1", False),
        (0, None, None, False),
        (0, 1, "d1", False),
        (0, 1, None, True),
        (0, None, "d1", True),
    ],
)
def test_rule_target_check(upgraded, all_people, group_id, device_id, ok: bool) -> None:
    engine, _ = upgraded
    sql = (
        "INSERT INTO alert_rules (name, channels, all_people, group_id, device_id, created_at) "
        "VALUES ('r', 'telegram', :a, :g, :d, :now)"
    )
    params = {"a": all_people, "g": group_id, "d": device_id}
    if ok:
        _exec(engine, sql, **params)
        return
    with pytest.raises(sa.exc.IntegrityError):
        _exec(engine, sql, **params)


def test_delivery_kind_check_admits_left_behind_only(upgraded) -> None:
    engine, _ = upgraded
    insert = (
        "INSERT INTO alert_deliveries (rule_id, event_kind, event_id, channel, sent_at, status) "
        "VALUES (3, :k, 1, 'telegram', :now, 'sent')"
    )
    _exec(engine, insert, k="left_behind")
    with pytest.raises(sa.exc.IntegrityError):
        _exec(engine, insert, k="person")
