#!/usr/bin/env python3
"""Seed the throwaway demo database the screenshot run drives.

Purpose    : Build a realistic, never-mocked dashboard state (two tracked
             devices with recent fixes, one place, one group, one alert rule,
             an app-lock PIN) so screenshots.py can photograph the real UI.
Inputs     : a temp root Path whose `demo.sqlite` the findplus imports already
             point at (screenshots.py:redirect_env runs first).
Outputs    : rows in that database. Nothing is returned.
Constraints: split out of screenshots.py to keep both files under the 300-line
             cap. Every write goes through the app's own repo/ingest helpers,
             never raw SQL, so a schema change breaks this loudly instead of
             writing a shape the daemon cannot read.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text

DEMO_PIN = "864213"  # >= security.MIN_PIN_LENGTH (6)
HOME_LAT, HOME_LON = 40.712800, -74.006000
DEMO_DEVICES = (("dev-google-1", "Moto Tag (car)"), ("dev-apple-1", "AirTag (keys)"))
# The screenshots are of a finished install, not a first run: without this the
# dashboard redirects every hash-less load to the setup wizard
# (web/app/main.js:checkOnboarding), the same trap cli/tests/ui/conftest.py hit.
SEEDED_COMPLETED_AT = "2026-01-01T00:00:00Z"


def _obs(device_id: str, name: str, lat: float, lon: float, minutes_ago: int):
    from findplus.findhub.types import RawObservation

    return RawObservation(
        device_id=device_id,
        device_name=name,
        latitude_e7=round(lat * 1e7),
        longitude_e7=round(lon * 1e7),
        observed_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
        accuracy_meters=15.0,
        source="crowdsourced",
        is_own_report=False,
    )


def _seed_devices_and_place() -> int:
    """Devices, then the place: ingest.py's geofence hook only evaluates
    places that already exist when the fixes are ingested."""
    from findplus.db.session import session_scope
    from findplus.ingest import upsert_device
    from findplus.places.repo import create_place
    from findplus.state import track_devices

    with session_scope() as session:
        for device_id, name in DEMO_DEVICES:
            upsert_device(session, device_id, name)
        track_devices(session, [d for d, _ in DEMO_DEVICES], exclusive=True)

    with session_scope() as session:
        place = create_place(
            session,
            name="Home",
            latitude_e7=round(HOME_LAT * 1e7),
            longitude_e7=round(HOME_LON * 1e7),
            radius_meters=200,
            color="#3b82f6",
            enter_confirmations=1,
            exit_confirmations=2,
        )
        return place.id


def _seed_fixes() -> None:
    from findplus.db.session import session_scope
    from findplus.ingest import ingest_observations

    ages = (40, 20, 0)
    google, apple = DEMO_DEVICES
    fixes = [
        _obs(google[0], google[1], HOME_LAT + i * 0.00003, HOME_LON, age)
        for i, age in enumerate(ages)
    ] + [
        _obs(apple[0], apple[1], HOME_LAT, HOME_LON + i * 0.00003, age)
        for i, age in enumerate(ages)
    ]
    with session_scope() as session:
        ingest_observations(session, fixes, fetched_at=datetime.now(UTC))


def _seed_group_and_lock() -> None:
    from findplus.appsettings import save_pin, set_lock_enabled
    from findplus.db.session import session_scope
    from findplus.groups.repo import create_group
    from findplus.security import hash_pin
    from findplus.state import set_setting

    with session_scope() as session:
        create_group(
            session,
            name="Family",
            color="#8b5cf6",
            quorum="majority",
            cluster_radius_meters=150,
            stale_after_minutes=90,
            member_ids=[d for d, _ in DEMO_DEVICES],
        )
    with session_scope() as session:
        set_setting(session, "onboarding.completed_at", SEEDED_COMPLETED_AT)
        salt, digest = hash_pin(DEMO_PIN)
        save_pin(session, salt, digest)
        set_lock_enabled(session, True)


def _seed_alert_rule(place_id: int) -> None:
    """Direct ORM insert: no alert-rule repo module exists yet."""
    from findplus.db.models_alerts import AlertRule
    from findplus.db.session import session_scope

    with session_scope() as session:
        session.add(
            AlertRule(
                name="Home arrival",
                place_id=place_id,
                device_id="dev-google-1",
                on_enter=True,
                on_exit=False,
                channels="webhook",
                cooldown_minutes=60,
                enabled=True,
                created_at=datetime.now(UTC),
            )
        )


def seed_demo_db(root: Path) -> None:
    place_id = _seed_devices_and_place()
    _seed_fixes()
    _seed_group_and_lock()
    _seed_alert_rule(place_id)

    engine = create_engine(f"sqlite+pysqlite:///{root / 'demo.sqlite'}")
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM devices")).scalar()
    assert count and count > 0, "seed_demo_db: devices table empty after seeding"
