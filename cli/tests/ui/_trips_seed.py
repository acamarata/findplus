"""A synthetic family, five synthetic days: the data the day-story UI tests read.

Purpose    : The shared UI database has two one-fix tags, so a school run, a
             gap day or a home-noise day cannot be shown from it. This seed
             builds those days for two trackers in a database of their own,
             so nothing here can change what other UI tests count.
Inputs     : JSON in FINDPLUS_TRIPS_DAYS: {"school": date, "gap": date,
             "noise": date, "empty": date, "single": date} (YYYY-MM-DD, UTC).
Outputs    : Devices TAG-SON ("Sam") and TAG-MOM ("Mia", group "Family"), the
             saved places Home, School, Grandma's and Work, and observations.
Constraints: Runs in a subprocess with FINDPLUS_STATE_DIR set to a throwaway
             directory. The server runs with TZ=UTC so wall-clock times in the
             tests are exactly the ones written here.
"""

# ruff: noqa: E501, RUF100

from __future__ import annotations

SEED_SCRIPT = """
import json, os
from datetime import UTC, datetime, timedelta
from findplus.db.migrate import upgrade_to_head
from findplus.db.models import Device
from findplus.db.session import session_scope
from findplus.groups.repo import create_group
from findplus.ingest import ingest_observations, upsert_device
from findplus.places.repo import create_place
from findplus.providers.google_findhub.types import RawObservation
from findplus.state import set_setting, track_devices

DAYS = json.loads(os.environ["FINDPLUS_TRIPS_DAYS"])
HOME, SCHOOL, GRAN, WORK = (41.10, -80.10), (41.13, -80.08), (41.05, -80.15), (41.08, -80.12)
upgrade_to_head()


def at(day, hhmm):
    h, m = map(int, hhmm.split(":"))
    return datetime.fromisoformat(day).replace(tzinfo=UTC) + timedelta(hours=h, minutes=m)


def jitter(i, spread=0.0002):
    return ((i * 37) % 11 - 5) / 5 * spread, ((i * 53) % 13 - 6) / 6 * spread


def line(a, b, n):
    return [(a[0] + (b[0] - a[0]) * k / (n + 1), a[1] + (b[1] - a[1]) * k / (n + 1)) for k in range(1, n + 1)]


def road(a, b, n):
    corner = (a[0], b[1])
    half = n // 2
    return line(a, corner, half) + [corner] + line(corner, b, n - half - 1)


def stay(day, start, end, step, centre, spread=0.0002):
    out, t, i = [], at(day, start), 0
    while t <= at(day, end):
        dl, dn = jitter(i, spread)
        out.append((t, centre[0] + dl, centre[1] + dn))
        t += timedelta(minutes=step)
        i += 1
    return out


def moving(day, start, step, pts):
    return [(at(day, start) + timedelta(minutes=step * k), p[0], p[1]) for k, p in enumerate(pts)]


def sam_school(day):
    fixes = stay(day, "00:05", "07:35", 15, HOME)
    fixes += moving(day, "07:42", 4, road(HOME, SCHOOL, 6))
    fixes += stay(day, "08:10", "15:00", 30, SCHOOL)
    fixes += moving(day, "15:06", 5, road(SCHOOL, HOME, 4))
    return fixes + stay(day, "15:40", "23:55", 30, HOME)


def sam_gap(day):
    fixes = stay(day, "00:05", "15:10", 45, HOME)
    fixes.append((at(day, "12:00"), 45.0, -70.0))
    fixes += stay(day, "16:40", "18:10", 15, GRAN)
    return fixes


def mia_school(day):
    fixes = stay(day, "00:05", "07:30", 30, HOME)
    fixes += moving(day, "07:36", 6, road(HOME, WORK, 5))
    fixes += stay(day, "08:15", "17:00", 30, WORK)
    fixes += moving(day, "17:06", 6, road(WORK, HOME, 5))
    return fixes + stay(day, "17:50", "23:50", 30, HOME)


sam = (
    sam_school(DAYS["school"]) + sam_gap(DAYS["gap"])
    + stay(DAYS["noise"], "00:00", "23:50", 18, HOME, 0.0005)
    + [(at(DAYS["single"], "10:00"), HOME[0] + 0.01, HOME[1])]
)
mia = mia_school(DAYS["school"])

with session_scope() as session:
    upsert_device(session, "TAG-SON", "Sam Tag")
    upsert_device(session, "TAG-MOM", "Mia Tag")
    for did, label, color in (("TAG-SON", "Sam", "#e7663f"), ("TAG-MOM", "Mia", "#4f8cf7")):
        dev = session.get(Device, did)
        dev.label, dev.icon, dev.color = label, "letter", color
    track_devices(session, ["TAG-SON", "TAG-MOM"], exclusive=True)
    for name, (la, lo) in (("Home", HOME), ("School", SCHOOL), ("Grandma's", GRAN), ("Work", WORK)):
        create_place(session, name=name, latitude_e7=round(la * 1e7), longitude_e7=round(lo * 1e7),
                     radius_meters=150, color="#3b82f6", enter_confirmations=1, exit_confirmations=1)

def raw(did, name, rows):
    return [RawObservation(device_id=did, device_name=name, latitude_e7=round(la * 1e7),
            longitude_e7=round(lo * 1e7), observed_at=t, accuracy_meters=20.0,
            source="crowdsourced", is_own_report=False) for t, la, lo in rows]

with session_scope() as session:
    ingest_observations(session, raw("TAG-SON", "Sam Tag", sam), fetched_at=datetime.now(UTC))
    ingest_observations(session, raw("TAG-MOM", "Mia Tag", mia), fetched_at=datetime.now(UTC))
    create_group(session, name="Family", color="#27ae60", quorum="majority",
                 cluster_radius_meters=150, stale_after_minutes=90,
                 member_ids=["TAG-SON", "TAG-MOM"])
    set_setting(session, "onboarding.completed_at", "2026-01-01T00:00:00Z")
"""
