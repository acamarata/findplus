"""Engine and session management.

Constraints:
    - WAL journal mode so the API can read while the poller writes.
    - `busy_timeout` avoids spurious "database is locked" under concurrent access.
    - `synchronous=FULL`: a committed fix survives power loss (see db/backup.py for the rest
      of the durability story).
    - After a failed startup check (db/integrity.py) new connections are `query_only`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from findplus.config import Settings, get_settings
from findplus.db.integrity import current_health


@lru_cache(maxsize=4)
def get_engine(database_url: str | None = None) -> Engine:
    settings: Settings = get_settings()
    url = database_url or settings.database_url
    if url.endswith(".sqlite") or "sqlite" in url:
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, future=True, echo=False)

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn: Any, _rec: Any) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=10000")
        # FULL: one extra fsync per commit (a few per poll). NORMAL in WAL can lose the
        # last commits on power loss, and a fix cannot always be fetched again.
        cur.execute("PRAGMA synchronous=FULL")
        if not current_health().ok:  # damaged at startup: look, never write
            cur.execute("PRAGMA query_only=ON")
        cur.close()

    return engine


def get_sessionmaker(database_url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(database_url), expire_on_commit=False, future=True)


@contextmanager
def session_scope(database_url: str | None = None) -> Iterator[Session]:
    """Transactional scope. Commits on success, rolls back on exception."""
    session = get_sessionmaker(database_url)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
