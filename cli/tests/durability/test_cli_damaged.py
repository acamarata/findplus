"""CLI write commands refuse to touch a database that fails its check."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlalchemy import func, select

from findplus.cli import main
from findplus.db.integrity import check_database, reset_health
from findplus.db.models import LocationObservation
from findplus.db.session import get_engine, session_scope
from tests.durability._damage import add_bulk, damage
from tests.durability._seed import seed_everything


@pytest.fixture
def damaged_db(session, tmp_db) -> Path:
    seed_everything(session, observations=12)
    session.commit()
    get_engine().dispose()
    db = Path(tmp_db)
    add_bulk(db)
    damage(db)
    assert not check_database(db).ok
    reset_health()
    return db


@pytest.mark.parametrize(
    "args",
    [
        ["db", "recompute-quality"],
        ["poll-now"],
        ["prune", "--before", "2026-12-31", "--yes"],
    ],
)
def test_write_commands_refuse_on_a_damaged_file(damaged_db, args) -> None:
    before = damaged_db.read_bytes()
    out = CliRunner().invoke(main, args)
    assert out.exit_code != 0
    assert "damaged" in out.output and "db restore" in out.output
    assert "Traceback" not in out.output
    assert damaged_db.read_bytes() == before  # not migrated, not written


def test_a_healthy_file_still_runs(tmp_db, session) -> None:
    seed_everything(session, observations=3)
    session.commit()
    reset_health()
    out = CliRunner().invoke(main, ["db", "recompute-quality"])
    assert out.exit_code == 0, out.output
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(LocationObservation)) == 3
