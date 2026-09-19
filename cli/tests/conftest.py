"""Shared fixtures. Tests NEVER touch the real Google account or the real database."""

from __future__ import annotations

import os
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

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
