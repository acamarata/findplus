"""The subprocess seed script `ui/conftest.py`'s `ui_db` fixture runs once per
session against the throwaway UI database (E13 stage 2 split, size cap: this
was a 78-line string literal inline in conftest.py).

Purpose    : Seed devices, a place, a group and a completed-onboarding stamp
             for the whole Playwright UI suite before `live_server` starts.
Inputs     : None -- runs as `python -c SEED_SCRIPT` with FINDPLUS_* env set
             by the `ui_env` fixture.
Outputs    : A migrated sqlite database with the fixture data below.
Constraints: Runs in a real subprocess, not in-process, so this stays a
             plain string rather than an importable function.
"""

from __future__ import annotations

SEED_SCRIPT = """
from datetime import UTC, datetime, timedelta
from findplus.db.migrate import upgrade_to_head
from findplus.db.models import Device
from findplus.db.session import session_scope
from findplus.findhub.types import RawObservation
from findplus.groups.repo import create_group
from findplus.ingest import ingest_observations, upsert_device
from findplus.places.repo import create_place
from findplus.state import set_setting, track_devices

upgrade_to_head()

HOME_LAT, HOME_LON = 41.100000, -80.100000


def obs(device_id, device_name, lat, lon):
    return RawObservation(
        device_id=device_id, device_name=device_name,
        latitude_e7=round(lat * 1e7), longitude_e7=round(lon * 1e7),
        observed_at=datetime.now(UTC) - timedelta(minutes=1),
        accuracy_meters=15.0, source="crowdsourced", is_own_report=False,
    )


with session_scope() as session:
    upsert_device(session, "TAG-HOME", "Home Tag")
    upsert_device(session, "TAG-AWAY", "Away Tag")
    upsert_device(session, "TAG-STALE", "Stale Tag")
    # Untracked on purpose: it gives the footer an Apple tracker to notice
    # (test_honesty_notices.py) without changing tracked_count for any other test.
    upsert_device(session, "TAG-AIR", "AirTag", provider="apple-find-my")
    # One device carries a real label, icon and colour rather than the 0007
    # defaults, so the badge, dialog, map and timeline tests have something
    # specific to assert (P2-E4-W3-S1-T6). The raw name stays "Home Tag";
    # every existing selector that matches on it still matches.
    home = session.get(Device, "TAG-HOME")
    home.label = "Ali's Keys"
    home.icon = "lucide:key"
    home.color = "#4f8cf7"
    track_devices(session, ["TAG-HOME", "TAG-AWAY", "TAG-STALE"], exclusive=True)

# The place must exist BEFORE the observations are ingested: ingest.py's
# geofence hook only evaluates places already on disk at ingest time.
with session_scope() as session:
    create_place(
        session, name="Home", latitude_e7=round(HOME_LAT * 1e7),
        longitude_e7=round(HOME_LON * 1e7), radius_meters=200,
        color="#3b82f6", enter_confirmations=1, exit_confirmations=1,
    )

with session_scope() as session:
    ingest_observations(
        session,
        [
            obs("TAG-HOME", "Home Tag", HOME_LAT, HOME_LON),
            obs("TAG-AWAY", "Away Tag", HOME_LAT + 0.00045, HOME_LON),
        ],
        fetched_at=datetime.now(UTC),
    )

# TAG-STALE is a tracked group member with no observation ever ingested --
# member_status() treats "no fix" the same as a fix older than stale_after.
with session_scope() as session:
    create_group(
        session, name="Family", color="#27ae60", quorum="majority",
        cluster_radius_meters=150, stale_after_minutes=90,
        member_ids=["TAG-HOME", "TAG-AWAY", "TAG-STALE"],
    )

# This suite drives a COMPLETED install. Without the stamp, main.js's
# onboarding check redirects every `page.goto("/")` to #/setup and hides
# #app-shell, so every dashboard assertion in this directory fails on an
# element the wizard is covering (P2-E11-W4-S1-T4). The wizard's own tests
# clear it per test through the `onboarding_incomplete` fixture below.
with session_scope() as session:
    set_setting(session, "onboarding.completed_at", "2026-01-01T00:00:00Z")
"""
