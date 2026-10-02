"""Migration 0013: one person per tracker, round trip, re-run, refusal and ORM parity.

Purpose : Prove the triggers keep a tracker in at most one person/pet group
          (any number of sets is fine), that downgrade to 0012 then upgrade
          again keeps every 0012 row with clean FK/integrity checks, that
          `findplus db upgrade` is a no-op at head, that the revision refuses
          to rebuild alert_rules with foreign keys enforced, and that every
          ORM column exists in the migrated schema.
Inputs  : tmp_path only; no real ~/.findplus, no network.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from click.testing import CliRunner

from findplus.config import reset_settings_cache
from findplus.db import models_alerts, models_people
from findplus.db.migrate import upgrade_to_head
from findplus.db.models import Base
from findplus.db.session import get_engine
from tests import migration_0013_seed as seed

#: Importing these registers their tables on Base for the ORM parity check.
_ORM_MODULES = (models_alerts, models_people)

_TRIGGERS = {
    "trg_one_person_per_device",
    "trg_one_person_per_device_move",
    "trg_one_person_per_device_kind",
}


@pytest.fixture
def head(tmp_path: Path):
    cfg, url, engine = seed.setup(tmp_path)
    seed.seed_0012(engine)
    get_engine.cache_clear()
    upgrade_to_head(url)
    get_engine.cache_clear()
    return cfg, url, seed.fk_engine(url)


def _exec(engine: sa.Engine, sql: str) -> None:
    with engine.begin() as conn:
        conn.execute(sa.text(sql), {"now": seed.NOW})


def _rejected(engine: sa.Engine, sql: str) -> None:
    with pytest.raises(sa.exc.IntegrityError, match="one_person_per_device"):
        _exec(engine, sql)


def _add_person(engine: sa.Engine, gid: int, name: str, kind: str = "person") -> None:
    _exec(
        engine,
        f"INSERT INTO groups (id, name, kind, created_at) VALUES ({gid}, '{name}', '{kind}', :now)",
    )


def test_triggers_exist_at_head(head) -> None:
    _cfg, _url, engine = head
    with engine.connect() as conn:
        names = {
            r[0]
            for r in conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type='trigger'"))
        }
    assert names >= _TRIGGERS


def test_a_second_person_for_one_tracker_is_rejected(head) -> None:
    _cfg, _url, engine = head
    _exec(engine, "UPDATE groups SET kind = 'person' WHERE id = 1")  # Zaid: d1, d2
    _add_person(engine, 3, "Ali")
    _rejected(engine, "INSERT INTO device_group (device_id, group_id) VALUES ('d1', 3)")
    _add_person(engine, 4, "Meong", kind="pet")
    _rejected(engine, "INSERT INTO device_group (device_id, group_id) VALUES ('d2', 4)")
    _exec(engine, "INSERT INTO device_group (device_id, group_id) VALUES ('d3', 3)")


def test_sets_never_conflict(head) -> None:
    _cfg, _url, engine = head
    _exec(engine, "UPDATE groups SET kind = 'person' WHERE id = 1")
    # d1 is already in person 1 and set 2; a third group that is a set is fine.
    _exec(engine, "INSERT INTO groups (id, name, created_at) VALUES (5, 'Car pool', :now)")
    _exec(engine, "INSERT INTO device_group (device_id, group_id) VALUES ('d1', 5)")


def test_moving_a_membership_into_a_second_person_is_rejected(head) -> None:
    _cfg, _url, engine = head
    _exec(engine, "UPDATE groups SET kind = 'person' WHERE id = 1")
    _add_person(engine, 3, "Ali")
    _exec(engine, "INSERT INTO device_group (device_id, group_id) VALUES ('d3', 3)")
    _rejected(
        engine, "UPDATE device_group SET group_id = 3 WHERE device_id = 'd1' AND group_id = 2"
    )
    # Moving a tracker from one person to another (leaving the first) is allowed.
    _exec(engine, "UPDATE device_group SET group_id = 3 WHERE device_id = 'd2' AND group_id = 1")


def test_turning_a_set_into_a_person_is_rejected_on_overlap(head) -> None:
    _cfg, _url, engine = head
    _exec(engine, "UPDATE groups SET kind = 'person' WHERE id = 1")  # d1 now in a person
    _rejected(engine, "UPDATE groups SET kind = 'person' WHERE id = 2")  # Family holds d1
    _exec(engine, "UPDATE groups SET name = 'Household' WHERE id = 2")  # other edits pass


def _new_shape_rows(engine: sa.Engine) -> None:
    _exec(engine, "UPDATE groups SET kind = 'person' WHERE id = 1")
    _exec(engine, "UPDATE devices SET role = 'shoes', carry_weight = 0.8 WHERE device_id = 'd1'")
    _exec(
        engine,
        "INSERT INTO alert_rules (id, name, all_people, channels, created_at) "
        "VALUES (9, 'everyone', 1, 'telegram', :now)",
    )
    for rule, kind in ((9, "group"), (3, "left_behind")):
        _exec(
            engine,
            "INSERT INTO alert_deliveries (rule_id, event_kind, event_id, channel, sent_at, "
            f"status) VALUES ({rule}, '{kind}', 77, 'telegram', :now, 'sent')",
        )
    _exec(
        engine,
        "INSERT INTO left_behind (group_id, device_id, anchor_lat_e7, anchor_lon_e7, state, "
        "started_observed_at) VALUES (1, 'd2', 1, 1, 'apart_pending', :now)",
    )


def test_downgrade_then_upgrade_round_trips(head) -> None:
    cfg, url, engine = head
    before = seed.counts(engine)
    rules = seed.dump(engine, "alert_rules", seed.RULE_COLS)
    deliveries = seed.dump(engine, "alert_deliveries", seed.DELIVERY_COLS)
    _new_shape_rows(engine)

    command.downgrade(cfg, "0012")
    assert seed.revision(engine) == "0012"
    assert seed.counts(engine) == before
    assert seed.dump(engine, "alert_rules", seed.RULE_COLS) == rules
    assert seed.dump(engine, "alert_deliveries", seed.DELIVERY_COLS) == deliveries
    assert seed.health(engine) == ([], "ok")
    with engine.connect() as conn:
        names = set(sa.inspect(conn).get_table_names())
    assert names.isdisjoint(seed.NEW_TABLES)

    get_engine.cache_clear()
    upgrade_to_head(url)
    get_engine.cache_clear()
    assert seed.revision(engine) == "0013"
    assert seed.counts(engine) == before
    assert seed.dump(engine, "alert_deliveries", seed.DELIVERY_COLS) == deliveries
    assert seed.health(engine) == ([], "ok")
    test_triggers_exist_at_head((cfg, url, engine))


def test_findplus_db_upgrade_is_idempotent_at_head(tmp_path: Path, monkeypatch) -> None:
    from findplus.cli.cmd_db import db_cmd

    monkeypatch.setenv("FINDPLUS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FINDPLUS_DATABASE_PATH", str(tmp_path / "state" / "findplus.sqlite"))
    reset_settings_cache()
    get_engine.cache_clear()
    try:
        runner = CliRunner()
        for _ in range(2):
            result = runner.invoke(db_cmd, ["upgrade"], catch_exceptions=False)
            assert result.exit_code == 0
        assert runner.invoke(db_cmd, ["current"]).output.strip().startswith("0013")
        engine = seed.fk_engine(f"sqlite:///{tmp_path / 'state' / 'findplus.sqlite'}")
        assert seed.health(engine) == ([], "ok")
    finally:
        reset_settings_cache()
        get_engine.cache_clear()


def _load_revision():
    import findplus.db

    versions = Path(findplus.db.__file__).parent / "migrations" / "versions"
    path = versions / "0013_people_and_quality.py"
    spec = importlib.util.spec_from_file_location("rev0013", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_refuses_to_rebuild_with_foreign_keys_enforced(tmp_path: Path) -> None:
    rev = _load_revision()
    engine = seed.fk_engine(f"sqlite:///{tmp_path / 'fk.sqlite'}")
    with engine.begin() as conn:
        # pysqlite only opens a real BEGIN on DML; once open, the PRAGMA is a no-op.
        conn.execute(sa.text("CREATE TABLE t (a INTEGER)"))
        conn.execute(sa.text("INSERT INTO t VALUES (1)"))
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx), pytest.raises(RuntimeError, match="foreign keys off"):
            rev._require_fk_off()


def test_every_orm_column_exists_in_the_migrated_schema(head) -> None:
    _cfg, _url, engine = head
    inspector = sa.inspect(engine)
    missing = [
        f"{table.name}.{col.name}"
        for table in Base.metadata.sorted_tables
        for col in table.columns
        if col.name not in {c["name"] for c in inspector.get_columns(table.name)}
    ]
    assert missing == []
