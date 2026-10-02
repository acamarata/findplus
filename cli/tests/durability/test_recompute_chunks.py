"""recompute-quality commits in chunks so a concurrent writer is not locked out."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from findplus.db.models_people import ObservationQuality
from findplus.db.session import get_engine, session_scope
from findplus.quality import store

T0 = datetime(2026, 9, 18, 8, 0, tzinfo=UTC)


def test_chunked_recompute_commits_in_pieces_and_scores_everything(tmp_db, session) -> None:
    from findplus.ingest import ingest_observations, upsert_device
    from tests.conftest import make_observation

    upsert_device(session, "d1", "Tracker", now=T0)
    ingest_observations(
        session,
        [
            make_observation(
                device_id="d1",
                device_name="Tracker",
                lat=41.0 + i * 1e-5,
                lon=-80.0,
                observed_at=T0 + timedelta(minutes=i),
            )
            for i in range(250)
        ],
        fetched_at=T0 + timedelta(days=1),
    )
    session.commit()
    seen: list[int] = []
    other = sqlite3.connect(Path(tmp_db), timeout=0.2)
    real = store.write_scores

    def spy(sess, scored, **kw):
        # between chunks the write lock must be free for a second connection
        if seen:
            other.execute("BEGIN IMMEDIATE")
            other.execute("ROLLBACK")
        n = real(sess, scored, **kw)
        seen.append(n)
        return n

    store.write_scores = spy
    try:
        with session_scope() as s:
            result = store.recompute(s, now=T0 + timedelta(days=2), commit_every=100)
    finally:
        store.write_scores = real
        other.close()
    assert result.rows == 250 and seen == [100, 100, 50]
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(ObservationQuality)) == 250
    get_engine().dispose()
