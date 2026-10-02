"""V7 and friends: the ingest hook scores fixes and holds unconfirmed jumps from the geofence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from findplus.db.models import LocationObservation, PlaceEvent
from findplus.db.models_people import ObservationQuality
from findplus.ingest import ingest_observations, upsert_device
from findplus.places.repo import create_place
from tests.conftest import make_observation
from tests.quality._vectors import ORIGIN
from tests.trips._synth import offset

DEV = "TAG-1"
START = datetime(2026, 9, 18, 4, 17, tzinfo=UTC)


def _setup(session) -> None:
    upsert_device(session, DEV, "Tag")
    far = offset(ORIGIN, 2500, 0)
    for name, pt in (("Home", ORIGIN), ("Far", far)):
        create_place(
            session,
            name=name,
            latitude_e7=round(pt[0] * 1e7),
            longitude_e7=round(pt[1] * 1e7),
            radius_meters=200,
            enter_confirmations=2,
        )


def _poll(session, minutes: float, north_m: float = 0.0, acc: float = 30.0) -> None:
    lat, lon = offset(ORIGIN, north_m, 0)
    when = START + timedelta(minutes=minutes)
    ob = make_observation(device_id=DEV, lat=lat, lon=lon, observed_at=when, accuracy=acc)
    ingest_observations(session, [ob], fetched_at=when + timedelta(seconds=20))
    session.flush()


def _enters(session, place: str) -> list[PlaceEvent]:
    from findplus.db.models import Place

    pid = session.scalar(select(Place.id).where(Place.name == place))
    return list(
        session.scalars(
            select(PlaceEvent).where(PlaceEvent.place_id == pid, PlaceEvent.event_type == "ENTER")
        )
    )


def _row(session, minutes: float) -> ObservationQuality:
    obs = session.scalar(
        select(LocationObservation).where(
            LocationObservation.observed_at == START + timedelta(minutes=minutes)
        )
    )
    return session.get(ObservationQuality, obs.id)


def test_v7_a_lone_jump_is_held_then_confirmed(session) -> None:
    _setup(session)
    _poll(session, 0)
    _poll(session, 1, 2500, acc=40)
    assert _row(session, 1).suspect and _row(session, 1).reasons == "jump_unconfirmed"
    assert _enters(session, "Far") == []  # held: no ENTER yet
    _poll(session, 2, 2520)  # C confirms B
    assert not _row(session, 1).suspect and _row(session, 1).corroborated_by is not None
    enters = _enters(session, "Far")
    assert len(enters) == 1
    assert enters[0].observed_at == START + timedelta(minutes=2)  # two confirmations: C's time


def test_v7_a_jump_that_comes_straight_back_never_enters(session) -> None:
    _setup(session)
    _poll(session, 0)
    _poll(session, 1, 2500, acc=40)
    _poll(session, 2, 60)  # back near A: B was a teleport
    assert "aba_teleport" in _row(session, 1).reasons and _row(session, 1).suspect
    assert _enters(session, "Far") == []
    assert not _row(session, 2).suspect


def test_a_real_fast_trip_enters_one_poll_late(session) -> None:
    _setup(session)
    _poll(session, 0)
    _poll(session, 1, 2500)  # fast: held
    assert _enters(session, "Far") == []
    _poll(session, 2, 5000)  # keeps going: the jump was real, B is released
    assert not _row(session, 1).suspect and _row(session, 1).reasons == ""
    assert _row(session, 2).reasons == "jump_unconfirmed"  # the newest fix waits in turn
    _poll(session, 3, 7500)
    assert _row(session, 2).reasons == "" and not _row(session, 2).suspect


def test_a_batch_with_the_whole_story_needs_no_hold(session) -> None:
    _setup(session)
    obs = []
    for minutes, north in ((0, 0), (1, 2500), (2, 2520)):
        lat, lon = offset(ORIGIN, north, 0)
        when = START + timedelta(minutes=minutes)
        obs.append(make_observation(device_id=DEV, lat=lat, lon=lon, observed_at=when))
    ingest_observations(session, obs, fetched_at=START + timedelta(minutes=3))
    assert not _row(session, 1).suspect
    assert len(_enters(session, "Far")) == 1


def test_a_held_fix_too_old_to_confirm_is_released_by_the_next_ingest(session) -> None:
    _setup(session)
    _poll(session, 0)
    _poll(session, 1, 2500)
    assert _row(session, 1).suspect
    _poll(session, 3 * 60, 2500)  # three hours later, same far place
    assert not _row(session, 1).suspect
    assert _enters(session, "Far")


def test_a_failing_quality_hook_never_loses_observations(session, monkeypatch) -> None:
    import findplus.ingest as ing

    def boom(*a, **k):
        raise RuntimeError("scoring bug")

    monkeypatch.setattr(ing, "plan_geofence_feed", boom)
    _setup(session)
    _poll(session, 0)
    assert session.scalar(select(LocationObservation.id)) is not None
