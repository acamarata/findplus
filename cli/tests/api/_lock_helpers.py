"""Shared fixtures and constants for the split `test_lock_api_*.py` modules.

Purpose    : test_lock_api.py grew past the 300-line cap (PRI rule 7) and was
             split by concern into guards/unlock/lockout/pin siblings in this
             package. Every one of those files needs the same locked-app
             client, so the fixtures live here once and are imported into
             each split module the same way tests.test_api.client is reused
             by tests.api.test_core_endpoints (see that file for precedent).
Inputs     : tmp_db (cli/tests/conftest.py) for an isolated database.
Outputs    : `store`/`client` fixtures, the `PIN`/`GATED` constants, and the
             `_set_pin` helper.
Constraints: keep import-only — no test functions live in this module.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from findplus.db.session import session_scope
from findplus.ingest import ingest_observations, upsert_device
from findplus.security import SessionStore
from findplus.state import track_devices
from tests.conftest import make_observation

PIN = "864213"

#: Every endpoint that must refuse to answer while locked.
GATED = [
    "/api/status",
    "/api/timeline",
    "/api/days",
    "/api/latest",
    "/api/devices",
    "/api/config",
    "/api/export?fmt=csv",
    "/api/poll-runs",
    "/api/settings",
]


@pytest.fixture
def store() -> SessionStore:
    return SessionStore()


@pytest.fixture
def client(tmp_db, store):
    from findplus.api import create_app

    with session_scope() as session:
        upsert_device(session, "TAG-001", "Moto Tag 2")
        track_devices(session, ["TAG-001"], exclusive=True)
        ingest_observations(
            session,
            [make_observation(minutes=0, lat=41.1), make_observation(minutes=20, lat=41.2)],
            fetched_at=datetime(2026, 9, 18, 13, 0, tzinfo=UTC),
        )
    return TestClient(create_app(store))


def _set_pin(client: TestClient, pin: str = PIN) -> None:
    assert client.post("/api/settings/pin", json={"new_pin": pin}).status_code == 200
