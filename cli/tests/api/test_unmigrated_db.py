"""An unmigrated database fails the lock gate CLOSED, with a typed 503 (CF-6).

Purpose    : `_current_lock_state()` backs SessionAuthMiddleware. It used to let
             OperationalError escape, so every gated request 500ed; answering
             "not locked" instead would have been worse, opening every gated
             route whenever the schema was missing.
Inputs     : An empty SQLite file that no migration has ever touched.
Outputs    : pytest assertions on the status code and the detail string.
Constraints: Never touches the real state directory — the database path and the
             state directory are both redirected into tmp_path.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def unmigrated_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db = tmp_path / "unmigrated.sqlite"
    db.touch()
    monkeypatch.setenv("FINDPLUS_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("FINDPLUS_DATABASE_PATH", str(db))

    from findplus.config import reset_settings_cache

    reset_settings_cache()
    from findplus.api import create_app

    # base_url pins a loopback Host on the daemon's own port: OriginGuardMiddleware
    # refuses anything else (wrong hostname or wrong port) with a 421 before the
    # lock gate is ever reached (CF-P2-3: a bare Host with no port is now refused too).
    # bound_host/bound_port (closeout C-M1) match it explicitly rather than
    # relying on get_settings() at creation time.
    return TestClient(
        create_app(bound_host="127.0.0.1", bound_port=8647), base_url="http://127.0.0.1:8647"
    )


def test_gated_route_returns_503_not_500_on_an_unmigrated_db(unmigrated_client) -> None:
    res = unmigrated_client.get("/api/devices")

    assert res.status_code == 503
    assert res.json()["detail"] == "Database not migrated. Run findplus db upgrade."


def test_gated_route_never_reads_an_unmigrated_db_as_unlocked(unmigrated_client) -> None:
    """Fail closed: a missing schema must not be answered as 200 or 401."""
    res = unmigrated_client.get("/api/devices")

    assert res.status_code not in (200, 401)


def test_public_routes_still_answer_on_an_unmigrated_db(unmigrated_client) -> None:
    """The repair path has to stay reachable, or the 503's advice is unusable."""
    assert unmigrated_client.get("/api/health").status_code == 200
