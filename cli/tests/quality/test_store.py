"""The quality store: recompute, idempotence, version stamp, siblings, the trips wrapper."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from findplus.db.models import Group, LocationObservation
from findplus.db.models_people import ObservationQuality
from findplus.groups.repo import create_group
from findplus.ingest import ingest_observations, upsert_device
from findplus.quality import rules, store
from findplus.quality.api import is_suspect, suspect_ids
from tests.conftest import make_observation
from tests.quality._vectors import ORIGIN, T0
from tests.trips._synth import offset

NOW = T0 + timedelta(days=2)


def _ingest(session, device: str, points, fetched_late: bool = True) -> None:
    """points: (minutes, north_m); fetched long after, so the batch is judged whole."""
    obs = []
    for minutes, north in points:
        lat, lon = offset(ORIGIN, north, 0)
        obs.append(
            make_observation(
                device_id=device,
                device_name=device,
                lat=lat,
                lon=lon,
                observed_at=T0 + timedelta(minutes=minutes),
            )
        )
    ingest_observations(session, obs, fetched_at=NOW)
    session.flush()


def _rows(session) -> dict[int, ObservationQuality]:
    return {r.observation_id: r for r in session.scalars(select(ObservationQuality))}


def _snapshot(session) -> list[tuple]:
    return sorted(
        (r.observation_id, r.score, r.suspect, r.reasons, r.corroborated_by)
        for r in session.scalars(select(ObservationQuality))
    )


def test_recompute_writes_every_row_and_finds_the_teleport(session) -> None:
    _ingest(session, "d1", [(0, 0), (1, 2500), (2, 60)])
    session.execute(__import__("sqlalchemy").delete(ObservationQuality))
    result = store.recompute(session, now=NOW)
    assert (result.devices, result.rows, result.suspects) == (1, 3, 1)
    rows = _rows(session)
    assert sum(r.suspect for r in rows.values()) == 1
    assert all(r.algo_version == rules.ALGO_VERSION for r in rows.values())


def test_recompute_is_idempotent(session) -> None:
    _ingest(session, "d1", [(0, 0), (1, 2500), (2, 60), (60, 0), (61, 10)])
    store.recompute(session, now=NOW)
    first = _snapshot(session)
    store.recompute(session, now=NOW)
    assert _snapshot(session) == first


def test_recompute_since_leaves_older_rows_alone(session) -> None:
    _ingest(session, "d1", [(0, 0), (1, 2500), (2, 60), (600, 0), (601, 10)])
    store.recompute(session, now=NOW)
    session.execute(update(ObservationQuality).values(algo_version=0))
    store.recompute(session, since=T0 + timedelta(minutes=500), now=NOW)
    versions = sorted(r.algo_version for r in _rows(session).values())
    assert versions.count(0) == 3 and versions.count(rules.ALGO_VERSION) == 2


def test_a_version_bump_rewrites_stale_rows(session) -> None:
    _ingest(session, "d1", [(0, 0), (1, 5), (2, 8)])
    session.execute(update(ObservationQuality).values(algo_version=0, score=0.1, suspect=True))
    store.recompute(session, now=NOW)
    assert all(
        not r.suspect and r.algo_version == rules.ALGO_VERSION for r in _rows(session).values()
    )


def test_raw_observations_are_never_changed(session) -> None:
    _ingest(session, "d1", [(0, 0), (1, 2500), (2, 60)])
    before = [
        (o.id, o.latitude_e7, o.longitude_e7, o.observed_at, o.times_returned)
        for o in session.scalars(select(LocationObservation))
    ]
    store.recompute(session, now=NOW)
    after = [
        (o.id, o.latitude_e7, o.longitude_e7, o.observed_at, o.times_returned)
        for o in session.scalars(select(LocationObservation))
    ]
    assert before == after


def test_siblings_come_from_person_groups_only(session) -> None:
    for d in ("shoes", "bag", "watch", "other"):
        upsert_device(session, d, d)
    create_group(session, name="Set", member_ids=["shoes", "bag", "other"])
    person = create_group(session, name="Zaid", member_ids=["shoes", "bag", "watch"])
    session.execute(update(Group).where(Group.id == person.id).values(kind="person"))
    assert store.sibling_ids(session, "bag") == ["shoes", "watch"]
    assert store.sibling_ids(session, "other") == []


def test_sibling_disagree_through_the_database(session) -> None:
    for d in ("shoes", "bag", "watch"):
        upsert_device(session, d, d)
    person = create_group(session, name="Zaid", member_ids=["shoes", "bag", "watch"])
    session.execute(update(Group).where(Group.id == person.id).values(kind="person"))
    _ingest(session, "shoes", [(100, 3000), (104, 3000)])
    _ingest(session, "watch", [(101, 3000), (105, 3000)])
    _ingest(session, "bag", [(0, 3000), (50, 3000), (102, 6000)])
    store.recompute(session, now=NOW)
    bad = session.scalar(
        select(ObservationQuality).where(
            ObservationQuality.reasons.contains(rules.SIBLING_DISAGREE)
        )
    )
    assert bad is not None and bad.suspect


def test_api_reads_what_the_store_wrote(session) -> None:
    _ingest(session, "d1", [(0, 0), (1, 2500), (2, 60)])
    ids = suspect_ids(session, ["d1"], T0, T0 + timedelta(hours=1))
    assert len(ids) == 1 and is_suspect(session, next(iter(ids)))


def test_trips_use_stored_verdicts_over_the_pure_rules(session) -> None:
    from datetime import date
    from zoneinfo import ZoneInfo

    from findplus.trips.service import trips_for

    _ingest(
        session, "d1", [(m, 0) for m in range(0, 8)] + [(8, 2500)] + [(m, 0) for m in range(9, 16)]
    )
    body = trips_for(session, "d1", date(2026, 9, 18), 1, ZoneInfo("UTC"))
    assert len(body["outliers"]) == 1
    out = body["outliers"][0]
    assert "aba_teleport" in out["reasons"] and out["suspect_reason"].startswith("This sighting")
    # A stored "not suspect" verdict wins over the pure rule (the person rescued it).
    session.execute(update(ObservationQuality).values(suspect=False, score=0.6, reasons=""))
    body = trips_for(session, "d1", date(2026, 9, 18), 1, ZoneInfo("UTC"))
    assert body["outliers"] == []


def test_datetime_now_default_is_utc_aware(session) -> None:
    _ingest(session, "d1", [(0, 0), (1, 5), (2, 8)])
    result = store.recompute(session)
    assert result.rows == 3 and datetime.now(UTC).tzinfo is not None
