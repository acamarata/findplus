"""A small but complete database for the durability tests (no network, fixed clock)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from findplus.alerts.channels_field import format_channels
from findplus.db.models import Device, Group
from findplus.db.models_alerts import AlertRule
from findplus.groups.repo import create_group
from findplus.ingest import ingest_observations, upsert_device
from findplus.places.repo import create_place
from tests.conftest import make_observation

START = datetime(2026, 9, 18, 8, 0, tzinfo=UTC)


def seed_everything(session, observations: int = 12) -> None:
    """Devices with roles, places with kinds, a person and a set group, rules, sightings."""
    for did, name in (("d-shoes", "Zaid Shoes"), ("d-bag", "Zaid Bag"), ("d-phone", "Ali Phone")):
        upsert_device(session, did, name, now=START)
    session.execute(
        update(Device)
        .where(Device.device_id == "d-shoes")
        .values(role="shoes", carry_weight=0.9, label="Red shoes", icon="lucide:footprints")
    )
    session.execute(update(Device).where(Device.device_id == "d-phone").values(role="phone"))
    home = create_place(
        session, name="Home", latitude_e7=410000000, longitude_e7=-800000000, radius_meters=150
    )
    school = create_place(
        session, name="School", latitude_e7=410200000, longitude_e7=-800100000, radius_meters=200
    )
    from findplus.db.models import Place

    session.execute(update(Place).where(Place.id == home.id).values(kind="home"))
    session.execute(update(Place).where(Place.id == school.id).values(kind="school"))
    person = create_group(session, name="Zaid", member_ids=["d-shoes", "d-bag"])
    session.execute(update(Group).where(Group.id == person.id).values(kind="person"))
    family = create_group(session, name="Family", member_ids=["d-shoes", "d-phone"], quorum="all")
    _rules(session, home.id, person.id, family.id)
    ingest_observations(
        session,
        [
            make_observation(
                device_id="d-shoes",
                device_name="Zaid Shoes",
                lat=41.0 + i * 0.0001,
                lon=-80.0,
                observed_at=START + timedelta(minutes=10 * i),
            )
            for i in range(observations)
        ],
        fetched_at=START + timedelta(days=1),
    )
    session.flush()


def _rules(session, home_id: int, person_id: int, family_id: int) -> None:
    now = START
    session.add_all(
        [
            AlertRule(
                name="Shoes at home",
                place_id=home_id,
                device_id="d-shoes",
                channels=format_channels(["telegram", "native"]),
                telegram_targets="111,-100222",
                created_at=now,
            ),
            AlertRule(
                name="Family arrives",
                place_id=home_id,
                group_id=family_id,
                channels="native",
                on_exit=False,
                cooldown_minutes=5,
                also_notify_members=True,
                created_at=now,
            ),
            AlertRule(
                name="Everyone", all_people=True, channels="webhook", enabled=False, created_at=now
            ),
        ]
    )
