"""Helpers that build and break a database file for the durability tests."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

PAGE = 4096


def add_bulk(db: Path) -> None:
    """Enough rows that pages 50-90 hold real data."""
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE filler (x BLOB)")
    conn.executemany("INSERT INTO filler VALUES (?)", [(os.urandom(3000),) for _ in range(300)])
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()


def damage(db: Path) -> None:
    """Overwrite pages 50-90 with random bytes."""
    with db.open("r+b") as fh:
        fh.seek(49 * PAGE)
        fh.write(os.urandom(41 * PAGE))
