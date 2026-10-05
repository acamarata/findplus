"""rebuild-derived keeps every sighting while another connection writes.

A replay chunk used to read first and write later, so a commit from the API or
the poller in between made SQLite refuse the write ("database is locked") and the
hook's events were silently lost until the next rebuild.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select

from findplus.config import get_settings
from findplus.db import models as m
from findplus.db.rebuild import rebuild_derived

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _shuttle(session, trips: int) -> None:
    """A tracker that goes in and out of one place `trips` times."""
    from findplus.ingest import ingest_observations, upsert_device
    from findplus.places.repo import create_place
    from tests.conftest import make_observation

    upsert_device(session, "d-x", "Tracker X", now=NOW)
    create_place(
        session, name="Hub", latitude_e7=410000000, longitude_e7=-800000000, radius_meters=150
    )
    fixes = ([(41.0, -80.0)] * 3 + [(41.5, -80.5)] * 3) * trips
    ingest_observations(
        session,
        [
            make_observation(
                device_id="d-x",
                device_name="Tracker X",
                lat=a,
                lon=b,
                observed_at=NOW + timedelta(minutes=10 * i),
            )
            for i, (a, b) in enumerate(fixes)
        ],
        fetched_at=NOW + timedelta(days=30),
    )


def _writer(db_path: str, stop: threading.Event, wrote: list[int]) -> None:
    """Another process's connection, committing small writes as fast as it can."""
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        while not stop.is_set():
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("test.noise", str(wrote[0]), NOW.isoformat()),
            )
            conn.commit()
            wrote[0] += 1
    finally:
        conn.close()


def test_rebuild_skips_nothing_while_another_connection_writes(tmp_db, session) -> None:
    _shuttle(session, trips=20)
    session.commit()
    expected = session.scalar(select(func.count()).select_from(m.PlaceEvent))
    assert expected >= 30
    session.execute(delete(m.PlaceEvent))
    session.execute(delete(m.PlaceState))
    session.commit()

    stop, wrote = threading.Event(), [0]
    thread = threading.Thread(target=_writer, args=(tmp_db, stop, wrote), daemon=True)
    thread.start()
    try:
        result = rebuild_derived(session, get_settings(), chunk=5, now=NOW)
    finally:
        stop.set()
        thread.join(15)

    assert wrote[0] > 0  # the writer really ran alongside the replay
    assert result.observations == 120
    assert result.failed == 0
    assert result.place_events == expected


def _baseline(session) -> int:
    _shuttle(session, trips=3)
    session.commit()
    return session.scalar(select(func.count()).select_from(m.PlaceEvent))


def test_a_lock_inside_a_hook_replays_the_chunk(tmp_db, session, monkeypatch) -> None:
    from sqlalchemy.exc import OperationalError

    from findplus.db import rebuild

    expected = _baseline(session)
    real, calls = rebuild.geofence_evaluate, [0]

    def flaky(s, lo, **kw):
        calls[0] += 1
        if calls[0] == 4:  # mid-chunk, after three sightings already wrote
            raise OperationalError("INSERT", {}, sqlite3.OperationalError("database is locked"))
        return real(s, lo, **kw)

    monkeypatch.setattr(rebuild, "geofence_evaluate", flaky)
    monkeypatch.setattr(rebuild.time, "sleep", lambda _s: None)
    result = rebuild_derived(session, get_settings(), chunk=5, now=NOW)
    assert result.failed == 0 and result.observations == 18
    assert result.place_events == expected


def test_a_hook_that_raises_is_counted_not_silent(tmp_db, session, monkeypatch) -> None:
    from findplus.db import rebuild

    _baseline(session)
    real = rebuild.run_person_hook

    def broken(s, lo, settings):
        if lo.id == 7:
            raise RuntimeError("boom")
        return real(s, lo, settings)

    monkeypatch.setattr(rebuild, "run_person_hook", broken)
    result = rebuild_derived(session, get_settings(), chunk=5, now=NOW)
    assert result.failed == 1 and result.observations == 18
