"""A realistic 17-tracker roster for the group UI tests.

Purpose    : The owner's first sign-in produced 17 devices, none with a single
             location yet (Google still locked), several sharing a name, a few
             with apostrophes, quotes or non-Latin characters. The seeded UI
             database has four devices, so these tests add the rest here and
             take them away again.
Inputs     : `ui_db` / `ui_env` (conftest.py): the throwaway database the live
             server reads. `tracked` is how many of the 17 are tracked.
Outputs    : `roster17(...)` context manager yielding the device dicts, and
             `forget_groups(ui_db, prefix)` for groups a test made.
Constraints: Never touches anything outside the throwaway database. Devices
             have no observations, which is the whole point.
"""

from __future__ import annotations

import contextlib
import sqlite3
import subprocess
import sys
from pathlib import Path

from .conftest import PROJECT_ROOT

PREFIX = "R17-"

NAMES = [
    "Ali Pixel 8a",
    "Ali Pixel 8a",
    "Zaid Shoes Red",
    "Ali's Keys — Café ☕",
    'O\'Brien "Bag"',
    "Tag 5",
    "Tag 6",
    "Tag 7",
    "Tag 8",
    "Tag 9",
    "Zaid Shoes Red",
    "Never Seen 11",
    "Never Seen 12",
    "Never Seen 13",
    "Never Seen 14",
    "Never Seen 15",
    "Never Seen 16",
]

_SEED = """
from findplus.db.session import session_scope
from findplus.ingest import upsert_device
from findplus.state import track_devices
import json, sys
names, tracked = json.loads(sys.argv[1]), int(sys.argv[2])
with session_scope() as s:
    ids = []
    for i, name in enumerate(names):
        did = f"{prefix}{i:02d}"
        upsert_device(s, did, name)
        ids.append(did)
    track_devices(s, ids[:tracked], exclusive=False)
"""


def devices(tracked: int) -> list[dict]:
    return [
        {"device_id": f"{PREFIX}{i:02d}", "name": n, "tracked": i < tracked}
        for i, n in enumerate(NAMES)
    ]


def forget_groups(ui_db: Path, prefix: str = "T17") -> None:
    conn = sqlite3.connect(ui_db)
    try:
        conn.execute(
            "DELETE FROM device_group WHERE group_id IN (SELECT id FROM groups WHERE name LIKE ?)",
            (prefix + "%",),
        )
        conn.execute(
            "DELETE FROM alert_rules WHERE group_id IN (SELECT id FROM groups WHERE name LIKE ?)",
            (prefix + "%",),
        )
        conn.execute("DELETE FROM groups WHERE name LIKE ?", (prefix + "%",))
        conn.commit()
    finally:
        conn.close()


@contextlib.contextmanager
def roster17(ui_db: Path, ui_env: dict, tracked: int):
    import json

    code = f"prefix = {PREFIX!r}\n" + _SEED
    subprocess.run(
        [sys.executable, "-c", code, json.dumps(NAMES), str(tracked)],
        check=True,
        capture_output=True,
        text=True,
        env=ui_env,
        cwd=PROJECT_ROOT,
    )
    try:
        yield devices(tracked)
    finally:
        forget_groups(ui_db)
        conn = sqlite3.connect(ui_db)
        try:
            conn.execute("DELETE FROM device_group WHERE device_id LIKE ?", (PREFIX + "%",))
            conn.execute("DELETE FROM devices WHERE device_id LIKE ?", (PREFIX + "%",))
            conn.commit()
        finally:
            conn.close()
