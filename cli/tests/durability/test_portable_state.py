"""The export carries settings, deliveries and digest runs; rebuild-derived restores the rest."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from click.testing import CliRunner
from sqlalchemy import delete, func, select

from findplus.cli import main
from findplus.config import get_settings
from findplus.db import models as m
from findplus.db.models_alerts import AlertDelivery, AlertRule
from findplus.db.models_people import DigestRun
from findplus.db.portable import export_lines
from findplus.db.portable_import import PortableImportError, import_lines
from findplus.db.rebuild import rebuild_derived
from findplus.state import get_setting, set_setting
from tests.durability._seed import seed_everything
from tests.durability.test_portable import _wipe

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _seed_state(session) -> None:
    seed_everything(session, observations=12)
    set_setting(session, "app.theme", "dark")
    set_setting(session, "lock_pin_hash", "HASH-SHOULD-NOT-LEAK")
    set_setting(session, "lock_enabled", "1")
    rule = session.scalars(select(AlertRule).where(AlertRule.name == "Shoes at home")).one()
    group = session.scalars(select(m.Group).where(m.Group.name == "Sam")).one()
    session.add(
        AlertDelivery(
            rule_id=rule.id,
            event_kind="device",
            event_id=1,
            sent_at=NOW,
            status="sent",
            channel="native",
            target="",
        )
    )
    session.add(
        DigestRun(
            group_id=group.id,
            local_date="2026-09-19",
            channel="native",
            target="",
            status="sent",
            sent_at=NOW,
        )
    )
    session.flush()


def _wipe_all(session) -> None:
    session.execute(delete(AlertDelivery))
    session.execute(delete(DigestRun))
    session.execute(delete(m.Setting))
    _wipe(session)


def test_settings_deliveries_and_digests_round_trip_without_the_lock(session) -> None:
    _seed_state(session)
    lines = list(export_lines(session))
    assert "SHOULD-NOT-LEAK" not in "\n".join(lines)
    kinds = {json.loads(x)["t"] for x in lines}
    assert {"setting", "alert_delivery", "digest_run"} <= kinds
    _wipe_all(session)
    with session.begin_nested():
        result = import_lines(session, lines)
    assert result.counts["alert_delivery"] == 1 and result.counts["digest_run"] == 1
    assert get_setting(session, "app.theme") == "dark"
    assert get_setting(session, "lock_enabled") is None  # the lock never travels
    delivery = session.scalars(select(AlertDelivery)).one()
    assert session.get(AlertRule, delivery.rule_id).name == "Shoes at home"
    assert session.scalars(select(DigestRun)).one().local_date == "2026-09-19"


def test_a_repeated_sighting_gets_a_plain_message(session) -> None:
    seed_everything(session, observations=3)
    lines = list(export_lines(session))
    dup = next(x for x in lines if json.loads(x)["t"] == "observation")
    _wipe_all(session)
    with pytest.raises(PortableImportError, match="same record twice"), session.begin_nested():
        import_lines(session, [*lines, dup])


def _commute(session) -> None:
    """A tracker that sits at a place, then leaves: an ENTER and an EXIT."""
    from datetime import timedelta

    from findplus.ingest import ingest_observations, upsert_device
    from findplus.places.repo import create_place
    from tests.conftest import make_observation

    upsert_device(session, "d-x", "Tracker X", now=NOW)
    create_place(
        session, name="Hub", latitude_e7=410000000, longitude_e7=-800000000, radius_meters=150
    )
    fixes = [(41.0, -80.0)] * 4 + [(41.5, -80.5)] * 4
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
        fetched_at=NOW + timedelta(days=1),
    )


def test_rebuild_derived_restores_events_and_sends_nothing(session) -> None:
    _commute(session)
    session.commit()
    before = session.scalar(select(func.count()).select_from(m.PlaceEvent))
    assert before > 0
    session.execute(delete(m.PlaceEvent))
    session.execute(delete(m.PlaceState))
    session.commit()
    result = rebuild_derived(session, get_settings(), now=NOW)
    assert result.observations == 8 and result.place_events == before
    pending = session.scalar(
        select(func.count()).select_from(m.PlaceEvent).where(m.PlaceEvent.notified_at.is_(None))
    )
    assert pending == 0


def test_rebuild_derived_command(tmp_db, session) -> None:
    _commute(session)
    session.commit()
    out = CliRunner().invoke(main, ["db", "rebuild-derived"])
    assert out.exit_code == 0, out.output
    assert "Replayed 8 sighting" in out.output and "Nothing was sent" in out.output
