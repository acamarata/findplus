"""Shared fixtures. Tests NEVER touch the real Google account or the real database."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

# Point every setting at a throwaway location BEFORE findplus.config is imported.
os.environ.setdefault("FINDPLUS_STATE_DIR", "/tmp/findplus-tests-state")


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A migrated, empty SQLite database scoped to one test."""
    from findplus.config import get_settings, reset_settings_cache
    from findplus.db.migrate import upgrade_to_head
    from findplus.db.session import get_engine, get_sessionmaker

    db_path = tmp_path / "test.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "state"))
    reset_settings_cache()
    get_engine.cache_clear()
    get_settings()
    upgrade_to_head()
    _ = get_sessionmaker()
    yield str(db_path)
    reset_settings_cache()
    get_engine.cache_clear()


@pytest.fixture
def session(tmp_db: str):
    from findplus.db.session import session_scope

    with session_scope() as s:
        yield s


@pytest.fixture
def eastern() -> ZoneInfo:
    return ZoneInfo("America/New_York")


@pytest.fixture
def base_time() -> datetime:
    """2026-09-18 08:00 UTC — a fixed anchor so tests never depend on 'now'."""
    return datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)


def make_observation(
    *,
    device_id: str = "TAG-001",
    device_name: str = "Moto Tag 2",
    lat: float = 41.123456,
    lon: float = -80.123456,
    observed_at: datetime | None = None,
    minutes: float = 0,
    accuracy: float | None = 25.0,
    source: str = "crowdsourced",
):
    """Build a RawObservation. `minutes` offsets from a fixed 2026-09-18 12:00 UTC base."""
    from findplus.findhub.types import RawObservation

    when = observed_at or (datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC) + timedelta(minutes=minutes))
    return RawObservation(
        device_id=device_id,
        device_name=device_name,
        latitude_e7=round(lat * 1e7),
        longitude_e7=round(lon * 1e7),
        observed_at=when,
        accuracy_meters=accuracy,
        source=source,
        is_own_report=False,
    )
