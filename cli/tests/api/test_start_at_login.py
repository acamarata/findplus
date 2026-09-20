"""POST /api/settings/app.start_at_login goes through findplus.service.

E1 confirmation pass F2: the handler shelled out to `findplus-daemon`, which is
the sidecar binary inside Find+.app and is on no PATH -- including the
sidecar's own, since this code runs in that process. Every toggle raised
OSError and returned 500, on every platform. api-contract.md:12 pins the
behaviour as "toggles the LaunchAgent RunAtLoad flag for com.acamarata.findplus
via `findplus.service`".
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from findplus.api import create_app


@pytest.fixture
def client(tmp_db, tmp_path, monkeypatch):
    # Never touch the real ~/Library/LaunchAgents.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return TestClient(create_app())


@pytest.fixture
def calls(monkeypatch):
    seen: list[tuple[str, dict]] = []
    from findplus.service import runtime

    monkeypatch.setattr(
        runtime, "install", lambda **kw: seen.append(("install", kw)), raising=False
    )
    monkeypatch.setattr(
        runtime, "uninstall", lambda *a, **kw: seen.append(("uninstall", {})), raising=False
    )
    return seen


def test_enabling_calls_the_service_facade_not_a_subprocess(client, calls) -> None:
    res = client.post("/api/settings/app.start_at_login", json={"value": True})

    assert res.status_code == 200, res.text
    assert res.json() == {"app.start_at_login": True}
    assert [name for name, _ in calls] == ["install"]
    assert calls[0][1]["confirmed"] is True
    assert calls[0][1]["program"].endswith("Find+.app/Contents/MacOS/findplus-daemon")


def test_disabling_uninstalls(client, calls) -> None:
    client.post("/api/settings/app.start_at_login", json={"value": True})
    res = client.post("/api/settings/app.start_at_login", json={"value": False})

    assert res.status_code == 200
    assert res.json() == {"app.start_at_login": False}
    assert [name for name, _ in calls] == ["install", "uninstall"]


def test_the_setting_round_trips_without_a_findplus_daemon_on_path(client, calls) -> None:
    """The regression itself: no PATH lookup is involved any more."""
    assert client.post("/api/settings/app.start_at_login", json={"value": True}).status_code == 200
    assert client.get("/api/settings/app.start_at_login").json() == {"app.start_at_login": True}


def test_a_service_manager_failure_is_a_500_with_the_reason(client, monkeypatch) -> None:
    from findplus.service import runtime

    def _boom(**kw):
        raise RuntimeError("launchctl bootstrap failed: Input/output error")

    monkeypatch.setattr(runtime, "install", _boom, raising=False)
    res = client.post("/api/settings/app.start_at_login", json={"value": True})

    assert res.status_code == 500
    assert "launchctl" in res.json()["detail"]


def test_no_subprocess_call_remains_in_the_handler() -> None:
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src" / "findplus" / "api" / "routes_settings.py"
    code = "\n".join(
        line for line in src.read_text().splitlines() if not line.lstrip().startswith("#")
    )
    # The docstring still NAMES findplus-daemon, to say why it is not called.
    assert "subprocess" not in code
    assert '"findplus-daemon"' not in code, "the handler must not shell out to the sidecar binary"
