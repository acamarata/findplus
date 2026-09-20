"""Programmatic Alembic runner.

Purpose : Let the CLI/daemon bring the schema to head without a shell round-trip.
Constraints: Schema changes go through Alembic revisions only. Never hand-edit the DB.
"""

from __future__ import annotations

import importlib.resources as _ir
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection

from findplus.config import get_settings
from findplus.db.session import get_engine

# Alembic narrates "Context impl SQLiteImpl" on every run; we only want warnings.
logging.getLogger("alembic").setLevel(logging.WARNING)


@contextmanager
def fk_disabled(connection: Connection) -> Iterator[None]:
    """Turn SQLite FK enforcement off for a migration run (CF-P2-15).

    Alembic's SQLite batch mode rebuilds an altered table by creating a new
    one, copying rows in, then dropping the original (see
    migrations/versions/0008_alert_channels_native.py for a migration that
    also guards itself directly). findplus.db.session turns
    `PRAGMA foreign_keys` ON for every connection, so that DROP TABLE runs an
    implicit DELETE with foreign keys enforced, which fires ON DELETE CASCADE
    on every child table and silently destroys their rows -- observations,
    group memberships, alert rules, anything cascading from the table being
    altered.

    `PRAGMA foreign_keys` is a documented no-op once a transaction is open
    (sqlite.org/pragma.html#pragma_foreign_keys), so the caller MUST enter
    this context on a connection with no pending BEGIN -- before opening the
    transaction the migration runs in, never inside one. Running the PRAGMA
    through `connection.exec_driver_sql()` would trigger SQLAlchemy 2.0's
    "future" Connection autobegin (any execute on a fresh Connection opens an
    implicit transaction), defeating the point -- so this goes straight to
    the raw DBAPI connection instead, the same way `db/session.py`'s
    `PRAGMA foreign_keys=ON` connect listener does.
    """
    dbapi_conn = connection.connection.dbapi_connection
    dbapi_conn.execute("PRAGMA foreign_keys=OFF")
    try:
        yield
    finally:
        dbapi_conn.execute("PRAGMA foreign_keys=ON")


def _config(database_url: str | None = None) -> Config:
    # Migrations live inside the package now (D2); locate them via importlib.resources
    # so this resolves in both editable and installed-wheel modes.
    return get_alembic_config(database_url or get_settings().database_url)


def upgrade_to_head(database_url: str | None = None) -> str:
    """Apply all pending migrations. Returns the resulting revision."""
    url = database_url or get_settings().database_url
    if url.startswith("sqlite") and ":memory:" not in url:
        Path(url.split("///", 1)[1]).parent.mkdir(parents=True, exist_ok=True)
    cfg = _config(url)
    engine = get_engine(url)
    # fk_disabled must wrap the connection BEFORE the transaction starts (see
    # its docstring), so this cannot use engine.begin() directly.
    with engine.connect() as connection, fk_disabled(connection), connection.begin():
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")
    return current_revision(url) or "head"


def current_revision(database_url: str | None = None) -> str | None:
    engine = get_engine(database_url or get_settings().database_url)
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def head_revision() -> str | None:
    return ScriptDirectory.from_config(_config()).get_current_head()


def is_up_to_date(database_url: str | None = None) -> bool:
    return current_revision(database_url) == head_revision()


def get_alembic_config(database_url: str) -> Config:
    """Build Alembic Config pointing at package-bundled migrations.
    Works from any cwd in both editable and installed-wheel modes."""
    migrations_path = str(_ir.files("findplus.db").joinpath("migrations"))
    cfg = Config()
    cfg.set_main_option("script_location", migrations_path)
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def run_migrations(database_url: str, target: str = "head") -> None:
    """Run Alembic to target revision. Idempotent at head.
    WARNING: target="base" (or any revision behind current) is a downgrade and is
    destructive (drops tables) — for tests only. Alembic's upgrade command cannot
    move backward, so "base" is routed to command.downgrade."""
    cfg = get_alembic_config(database_url)
    if target == "base":
        command.downgrade(cfg, target)
    else:
        command.upgrade(cfg, target)
