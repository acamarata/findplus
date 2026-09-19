"""Programmatic Alembic runner.

Purpose : Let the CLI/daemon bring the schema to head without a shell round-trip.
Constraints: Schema changes go through Alembic revisions only. Never hand-edit the DB.
"""

from __future__ import annotations

import importlib.resources as _ir
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from findplus.config import get_settings
from findplus.db.session import get_engine

# Alembic narrates "Context impl SQLiteImpl" on every run; we only want warnings.
logging.getLogger("alembic").setLevel(logging.WARNING)


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
    with engine.begin() as connection:
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
