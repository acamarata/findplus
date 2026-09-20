"""`findplus start` single-run state machine (P2-E7-W2-S1-T1).

Purpose    : Pin specs/service-and-settings.md § 1 — branch A exits 4, branch B
             discovers, prints, auto-tracks and installs in one process, and
             Apple-only sign-in is not branch A.
Inputs     : CliRunner invocations of `start` with the providers monkeypatched.
Outputs    : Assertions on exit codes, console text and facade calls.
Constraints: Never touches the real ~/.findplus, a browser or the network; the
             two providers are always stubbed.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from findplus.cli.main import main
from findplus.config import get_settings


@pytest.fixture(autouse=True)
def _no_browser(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    return opened


class _FakeDevice:
    def __init__(self, device_id: str, name: str) -> None:
        self.device_id = device_id
        self.name = name


def _no_google(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "findplus.providers.google_findhub.bootstrap.describe_stored_auth",
        lambda: {"exists": False},
    )


def _google_with(monkeypatch: pytest.MonkeyPatch, devices: list[_FakeDevice]) -> None:
    monkeypatch.setattr(
        "findplus.providers.google_findhub.bootstrap.describe_stored_auth",
        lambda: {"exists": True},
    )
    monkeypatch.setattr(
        "findplus.providers.google_findhub.client.FindHubClient.list_devices",
        lambda self: devices,
    )


def _write_apple_account() -> None:
    settings = get_settings()
    settings.ensure_dirs()
    (settings.state_dir / "apple-account.json").write_text("{}", encoding="utf-8")


def _stub_install(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []
    monkeypatch.setattr("findplus.service.is_installed", lambda: False)
    monkeypatch.setattr("findplus.service.install", lambda *a, **k: calls.append(k))
    monkeypatch.setattr("findplus.service.install_watchdog", lambda *a, **k: None)
    return calls


def _spy_track_all(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    from findplus import state as state_mod

    seen: list[bool] = []
    real = state_mod.track_all

    def _wrapped(session):
        seen.append(True)
        return real(session)

    monkeypatch.setattr("findplus.state.track_all", _wrapped)
    return seen


# --------------------------------------------------------------- branch A
def test_start_not_signed_in_exits_4(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _no_google(monkeypatch)
    install_calls = _stub_install(monkeypatch)

    result = CliRunner().invoke(main, ["start", "--yes"])

    assert result.exit_code == 4, result.output
    assert "Find+ is not signed in yet. Run:" in result.output
    assert "  findplus auth       (or findplus setup for a guided walkthrough)" in result.output
    assert "  findplus start" in result.output
    assert install_calls == []


def test_start_apple_only_is_not_branch_a(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    _no_google(monkeypatch)
    _write_apple_account()
    monkeypatch.setattr(
        "findplus.providers.apple_findmy.provider.AppleFindMyProvider.list_devices",
        lambda self: [_FakeDevice("APPLE-1", "AirTag")],
    )
    install_calls = _stub_install(monkeypatch)

    result = CliRunner().invoke(main, ["start", "--yes"])

    assert result.exit_code != 4, result.output
    assert result.exit_code == 0, result.output
    assert "AirTag" in result.output
    assert len(install_calls) == 1

    from findplus.db.models import Device
    from findplus.db.session import session_scope

    with session_scope() as s:
        row = s.get(Device, "APPLE-1")
        assert row is not None
        assert row.provider == "apple-find-my"


# --------------------------------------------------------------- branch B
def test_start_discovers_prints_and_tracks_all_then_installs(
    tmp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    _google_with(monkeypatch, [_FakeDevice("TAG-1", "Keys")])
    install_calls = _stub_install(monkeypatch)
    tracked_calls = _spy_track_all(monkeypatch)

    result = CliRunner().invoke(main, ["start", "--yes"])

    assert result.exit_code == 0, result.output
    assert "DEVICE ID" in result.output
    assert "Keys" in result.output
    assert "Now tracking all 1 device(s)." in result.output
    assert tracked_calls == [True]
    assert len(install_calls) == 1


def test_start_no_track_all_skips_tracking_but_still_installs(
    tmp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    _google_with(monkeypatch, [_FakeDevice("TAG-1", "Keys")])
    install_calls = _stub_install(monkeypatch)
    tracked_calls = _spy_track_all(monkeypatch)

    result = CliRunner().invoke(main, ["start", "--yes", "--no-track-all"])

    assert result.exit_code == 0, result.output
    assert "DEVICE ID" in result.output
    assert "Now tracking all" not in result.output
    assert "Nothing is being tracked yet. Choose what to poll:" in result.output
    assert tracked_calls == []
    assert len(install_calls) == 1


def test_start_both_providers_combine_into_one_table(
    tmp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    _google_with(monkeypatch, [_FakeDevice("TAG-1", "Keys")])
    _write_apple_account()
    monkeypatch.setattr(
        "findplus.providers.apple_findmy.provider.AppleFindMyProvider.list_devices",
        lambda self: [_FakeDevice("APPLE-1", "AirTag")],
    )
    _stub_install(monkeypatch)

    result = CliRunner().invoke(main, ["start", "--yes"])

    assert result.exit_code == 0, result.output
    assert "Keys" in result.output
    assert "AirTag" in result.output
    assert "Now tracking all 2 device(s)." in result.output

    from findplus.db.session import session_scope
    from findplus.state import get_tracked_devices

    with session_scope() as s:
        assert {d.device_id for d in get_tracked_devices(s)} == {"TAG-1", "APPLE-1"}


def test_start_help_lists_no_track_all(tmp_db) -> None:
    result = CliRunner().invoke(main, ["start", "--help"])
    assert result.exit_code == 0, result.output
    assert "--no-track-all" in result.output
