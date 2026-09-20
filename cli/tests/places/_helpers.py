"""Shared seed helpers for the places/repo test suite.

Purpose    : One definition of the device fixture and the raw-observation
             builder used by test_repo.py and test_repo_events.py, so
             splitting test_repo.py under the 300-line cap (PRI rule 7) does
             not duplicate them. `_devices` is autouse where it is IMPORTED,
             which is why it lives here and not in a conftest.py: the other
             files in this package seed their own devices.
Inputs     : The tmp_db-backed `session` fixture from cli/tests/conftest.py.
Outputs    : n/a (test-only builder).
Constraints: test-only; never imported by cli/src.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from findplus.db.models import Device, LocationObservation


@pytest.fixture(autouse=True)
def _devices(session):
    for device_id, name in (("dev1", "Tag1"), ("dev2", "Tag2")):
        session.add(
            Device(
                device_id=device_id,
                name=name,
                is_tracked=False,
                first_seen_at=datetime.now(UTC),
                last_seen_at=datetime.now(UTC),
            )
        )
    session.flush()


def make_observation(session, device_id: str = "dev1", when: datetime | None = None) -> int:
    when = when or datetime.now(UTC)
    obs = LocationObservation(
        device_id=device_id,
        device_name="Tag",
        latitude_e7=0,
        longitude_e7=0,
        observed_at=when,
        first_fetched_at=when,
        last_fetched_at=when,
        times_returned=1,
    )
    session.add(obs)
    session.flush()
    return obs.id
