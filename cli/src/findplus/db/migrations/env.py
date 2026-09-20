"""Alembic environment. Reads the database URL from findplus settings."""

from __future__ import annotations

from alembic import context
from sqlalchemy import pool

from findplus.config import get_settings
from findplus.db.migrate import fk_disabled
from findplus.db.models import Base
from findplus.db.session import get_engine

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection", None)
    if connectable is None:
        connectable = get_engine(_url())
    if hasattr(connectable, "connect"):
        # A fresh Engine: no transaction is open yet on this connection, so
        # fk_disabled's PRAGMA actually takes effect here (CF-P2-15). Covers
        # run_migrations() and any direct command.upgrade()/downgrade() call
        # (e.g. the migration test suite) that doesn't pre-open a connection.
        with connectable.connect() as connection, fk_disabled(connection):
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    else:
        # migrate.py's upgrade_to_head() already disabled FK enforcement on
        # this connection before opening the transaction that wraps this
        # whole run; PRAGMA foreign_keys is a no-op once a transaction is
        # open, so there is nothing to toggle here.
        context.configure(
            connection=connectable, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

_ = pool
