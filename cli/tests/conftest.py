"""Shared fixtures. Tests NEVER touch the real Google account or the real database."""

from __future__ import annotations

import os
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from findplus.ingest import ingest_observations, upsert_device

# Point every setting at a throwaway location BEFORE findplus.config is imported.
os.environ.setdefault("FINDPLUS_STATE_DIR", "/tmp/findplus-tests-state")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-skip `@pytest.mark.posix_only` tests on Windows.

    Purpose: a single place to skip the tests that assert exact POSIX mode
    bits (chmod/umask/uid) — Windows has no such concept, and
    `findplus.cli.doctor_perms` reports those checks as not-applicable there
    rather than false-failing (E14 Windows CI repair). Declared once here so
    ~15 call sites across several files don't each repeat their own
    `skipif(os.name == "nt", ...)`.
    """
    if os.name != "nt":
        return
    skip_posix = pytest.mark.skip(reason="POSIX permission bits are not enforced on Windows")
    for item in items:
        if "posix_only" in item.keywords:
            item.add_marker(skip_posix)


#: Where a TestClient pretends to be talking to. Starlette's default is
#: "http://testserver", which OriginGuardMiddleware answers with 421 because
#: it is not a loopback name — exactly the DNS-rebinding case it exists to
#: refuse. Every client in this suite therefore speaks as a loopback browser
#: does; the guard's own rejections are tested by setting Host explicitly.
LOOPBACK_BASE_URL = "http://127.0.0.1:8647"


def _default_testclient_to_loopback() -> None:
    """Make LOOPBACK_BASE_URL the default base_url for every TestClient."""
    from starlette.testclient import TestClient

    original = TestClient.__init__
    if getattr(original, "_findplus_loopback", False):
        return

    def patched(self, app, *args, **kwargs):
        kwargs.setdefault("base_url", LOOPBACK_BASE_URL)
        original(self, app, *args, **kwargs)

    patched._findplus_loopback = True
    TestClient.__init__ = patched


_default_testclient_to_loopback()


@pytest.fixture(autouse=True)
def _block_non_loopback_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    """PROMPT.md §2 invariant 3: tests never touch the network.

    Patches both `connect` and `connect_ex` (either can open a real socket) so
    no test path can reach a real host. Only inspects (host, port)-shaped
    addresses (AF_INET/AF_INET6): a local AF_UNIX socket (Playwright's own IPC
    to the browser it launches) is a plain str address, never a tuple, so it
    is never mistaken for an outbound network call. Loopback (127.0.0.0/8,
    ::1, "localhost") stays open so Playwright/uvicorn traffic still works.
    """
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _blocked_host(address: object) -> str | None:
        if not (isinstance(address, tuple) and address):
            return None
        host = address[0]
        if host in ("::1", "localhost"):
            return None
        if isinstance(host, str) and host.startswith("127."):
            return None
        return str(host)

    def guarded_connect(self, address):
        host = _blocked_host(address)
        if host is not None:
            raise RuntimeError(f"network access blocked in tests: {host}")
        return real_connect(self, address)

    def guarded_connect_ex(self, address):
        host = _blocked_host(address)
        if host is not None:
            raise RuntimeError(f"network access blocked in tests: {host}")
        return real_connect_ex(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)


@pytest.fixture(autouse=True)
def _isolate_bind_env_vars() -> None:
    """Undo whatever a test's `serve --host/--port` invocation exported.

    `_bind_or_exit` (cmd_serve.py, CF-P2-3) writes FINDPLUS_HOST/FINDPLUS_PORT
    straight into `os.environ` on purpose -- OriginGuardMiddleware calls
    `get_settings()` fresh on every request, so a `--port` override has to
    reach it that way, and that is production behavior this suite must not
    weaken. But `os.environ` is not test-scoped like `monkeypatch.setenv` is:
    any test that runs `serve`/`cmd_service.serve` through Click's CliRunner
    (test_sigterm.py's `--port 8641` case, not through `_bind_or_exit`
    directly the way test_serve_exclusive.py's own dedicated cases restore
    it) leaves that value set for every test that runs afterward in the same
    process. Every later `client` fixture still hard-codes Host 127.0.0.1:8647
    (LOOPBACK_BASE_URL below), so the leaked port mismatches it and
    OriginGuardMiddleware refuses the request with 421 -- ~90 unrelated
    failures across test_api*.py, test_multi_device_api.py and others,
    order-dependent on whichever test ran last (CF-P2-3 follow-up, 2026-09-22).
    One autouse fixture here, rather than a fix in that one test file, so any
    other direct os.environ write -- present or future -- gets the same
    snapshot/restore.
    """
    before_port = os.environ.get("FINDPLUS_PORT")
    before_host = os.environ.get("FINDPLUS_HOST")
    try:
        yield
    finally:
        if before_port is None:
            os.environ.pop("FINDPLUS_PORT", None)
        else:
            os.environ["FINDPLUS_PORT"] = before_port
        if before_host is None:
            os.environ.pop("FINDPLUS_HOST", None)
        else:
            os.environ["FINDPLUS_HOST"] = before_host


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A migrated, empty SQLite database scoped to one test."""
    from findplus.config import get_settings, reset_settings_cache
    from findplus.db.migrate import upgrade_to_head
    from findplus.db.session import get_engine, get_sessionmaker

    db_path = tmp_path / "test.sqlite"
    monkeypatch.setenv("FINDPLUS_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("FINDPLUS_STATE_DIR", str(tmp_path / "state"))
    reset_settings_cache()
    get_engine.cache_clear()
    get_settings()
    upgrade_to_head()
    _ = get_sessionmaker()
    yield str(db_path)
    reset_settings_cache()
    get_engine.cache_clear()


@pytest.fixture
def session(tmp_db: str):
    from findplus.db.session import session_scope

    with session_scope() as s:
        yield s


@pytest.fixture
def eastern() -> ZoneInfo:
    return ZoneInfo("America/New_York")


@pytest.fixture
def base_time() -> datetime:
    """2026-09-18 08:00 UTC — a fixed anchor so tests never depend on 'now'."""
    return datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)


def make_observation(
    *,
    device_id: str = "TAG-001",
    device_name: str = "Moto Tag 2",
    lat: float = 41.123456,
    lon: float = -80.123456,
    observed_at: datetime | None = None,
    minutes: float = 0,
    accuracy: float | None = 25.0,
    source: str = "crowdsourced",
):
    """Build a RawObservation. `minutes` offsets from a fixed 2026-09-18 12:00 UTC base."""
    from findplus.findhub.types import RawObservation

    when = observed_at or (datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC) + timedelta(minutes=minutes))
    return RawObservation(
        device_id=device_id,
        device_name=device_name,
        latitude_e7=round(lat * 1e7),
        longitude_e7=round(lon * 1e7),
        observed_at=when,
        accuracy_meters=accuracy,
        source=source,
        is_own_report=False,
    )


@pytest.fixture
def register_provider(monkeypatch: pytest.MonkeyPatch):
    """Inject a fake provider into the registry, undone automatically after the test.

    Shared by the poller and multi-device suites, which each had an identical
    copy before the test_poller.py split.
    """

    def _register(name: str, provider) -> None:
        from findplus.providers import base

        monkeypatch.setitem(base._REGISTRY, name, provider)

    return _register


@pytest.fixture
def selected(tmp_db):
    """One tracked device (TAG-001) on the fake `test-fake` provider."""
    from findplus.db.session import session_scope
    from findplus.ingest import upsert_device
    from findplus.state import track_devices

    with session_scope() as session:
        upsert_device(session, "TAG-001", "Moto Tag 2", provider="test-fake")
        track_devices(session, ["TAG-001"], exclusive=True)
    return "TAG-001"


# The seeded local-API client used by the contract tests. It lives here, not in
# test_api.py, so test_api.py and test_api_exports.py (split under PRI rule 7)
# share one definition of the seed; files with their own `client` override it.
@pytest.fixture
def client(tmp_db):
    from findplus.api import create_app
    from findplus.db.session import session_scope
    from findplus.state import track_devices

    with session_scope() as session:
        upsert_device(session, "TAG-001", "Moto Tag 2")
        track_devices(session, ["TAG-001"], exclusive=True)
        ingest_observations(
            session,
            [
                make_observation(minutes=0, lat=41.100),
                make_observation(minutes=17, lat=41.110),
                make_observation(minutes=63, lat=41.140),  # 46-minute gap
            ],
            fetched_at=datetime(2026, 9, 18, 13, 5, tzinfo=UTC),
        )
    return TestClient(create_app())


@pytest.fixture
def locked_client(client: TestClient):
    """`client` with the app lock engaged (PIN set, session cleared).

    Setting a PIN auto-issues the caller a fresh session cookie (routes_settings.py
    re-signs-in whoever just set it), so the cookie jar is cleared afterwards to
    make this client an anonymous, locked-out caller for the rest of the test.
    """
    pin = "000000"
    resp = client.post("/api/settings/pin", json={"new_pin": pin})
    assert resp.status_code == 200, resp.text
    client.cookies.clear()
    status = client.get("/api/lock/status").json()
    assert status["locked"] is True, f"lock did not activate: {status}"
    try:
        yield client
    finally:
        client.post("/api/lock/unlock", json={"pin": pin})
