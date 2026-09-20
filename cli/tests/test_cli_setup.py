"""`findplus setup`, the headless text wizard (P2-E7-W2-S1-T6).

Purpose    : Pin specs/onboarding.md § 6 -- `--yes` completes without a single
             prompt and changes nothing but the completion stamp, an
             interactive run tracks exactly what was chosen, and a second run
             is safe.
Inputs     : CliRunner invocations against a tmp_db, with the Google client and
             the `auth` command stubbed.
Outputs    : pytest assertions on exit codes, console text and the database.
Constraints: Never touches the real ~/.findplus, a browser or the network.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from findplus.appsettings import load_settings
from findplus.cli.main import main
from findplus.db.models import Group
from findplus.db.session import session_scope
from findplus.state import get_setting, get_tracked_devices


class _FakeDevice:
    def __init__(self, device_id: str, name: str) -> None:
        self.device_id = device_id
        self.name = name


@pytest.fixture
def two_devices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "findplus.providers.google_findhub.client.FindHubClient.list_devices",
        lambda self: [_FakeDevice("TAG-1", "Alpha"), _FakeDevice("TAG-2", "Bravo")],
    )


@pytest.fixture
def stub_auth(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    called: list[str] = []
    monkeypatch.setattr(
        "findplus.cli.cmd_auth.auth.callback", lambda provider: called.append(provider)
    )
    return called


def _completed_at() -> str | None:
    with session_scope() as session:
        return get_setting(session, "onboarding.completed_at")


# ------------------------------------------------------------------ --yes
def test_yes_fresh_state_completes_and_changes_nothing_else(tmp_db) -> None:
    result = CliRunner().invoke(main, ["setup", "--yes"])

    assert result.exit_code == 0, result.output
    assert "Find+ is not affiliated with Apple or Google" in result.output
    assert "Setup complete. Run `findplus start` to begin polling." in result.output
    assert _completed_at() is not None

    with session_scope() as session:
        assert get_tracked_devices(session) == []
        assert session.query(Group).count() == 0
        assert load_settings(session).pin_configured is False


def test_yes_never_prompts(tmp_db) -> None:
    """A prompt with no stdin would abort; an exit 0 on empty input proves none ran."""
    result = CliRunner().invoke(main, ["setup", "--yes"], input="")

    assert result.exit_code == 0, result.output
    assert "Run `findplus auth` later to sign in." in result.output
    assert "Tracked nothing." in result.output
    assert "Add places from the dashboard." in result.output


def test_yes_is_idempotent_and_restamps(tmp_db) -> None:
    first = CliRunner().invoke(main, ["setup", "--yes"])
    stamped_first = _completed_at()

    second = CliRunner().invoke(main, ["setup", "--yes"])

    assert (first.exit_code, second.exit_code) == (0, 0), second.output
    assert stamped_first is not None
    assert _completed_at() > stamped_first


# ------------------------------------------------------------ interactive
def test_interactive_tracks_one_of_two_devices(tmp_db, two_devices, stub_auth: list[str]) -> None:
    result = CliRunner().invoke(main, ["setup"], input="y\nn\n1\nn\nn\nn\n")

    assert result.exit_code == 0, result.output
    assert stub_auth == ["google-find-hub"]
    assert "1. Alpha (TAG-1)" in result.output
    assert "2. Bravo (TAG-2)" in result.output

    with session_scope() as session:
        assert [d.device_id for d in get_tracked_devices(session)] == ["TAG-1"]


def test_interactive_all_tracks_everything(tmp_db, two_devices, stub_auth: list[str]) -> None:
    result = CliRunner().invoke(main, ["setup"], input="n\nn\nall\nn\nn\nn\n")

    assert result.exit_code == 0, result.output
    assert stub_auth == []
    assert "Now tracking all 2 device(s)." in result.output


def test_interactive_creates_a_group(tmp_db, two_devices, stub_auth: list[str]) -> None:
    result = CliRunner().invoke(main, ["setup"], input="n\nn\nall\ny\nFamily\n1,2\nn\nn\n")

    assert result.exit_code == 0, result.output
    assert "Created group 'Family' with 2 member(s)." in result.output

    with session_scope() as session:
        assert [g.name for g in session.query(Group).all()] == ["Family"]


def test_a_failed_google_sign_in_does_not_end_the_wizard(
    tmp_db, two_devices, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`auth` exits 1 when Chrome is missing; the rest of setup still runs."""

    def _exit(provider):
        raise SystemExit(1)

    monkeypatch.setattr("findplus.cli.cmd_auth.auth.callback", _exit)

    result = CliRunner().invoke(main, ["setup"], input="y\nn\nall\nn\nn\nn\n")

    assert result.exit_code == 0, result.output
    assert "Sign-in did not finish. Run `findplus auth` later." in result.output
    assert "Setup complete." in result.output


def test_a_provider_that_cannot_list_devices_skips_that_step(
    tmp_db, stub_auth: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(self):
        raise RuntimeError("session expired")

    monkeypatch.setattr(
        "findplus.providers.google_findhub.client.FindHubClient.list_devices", _raise
    )

    result = CliRunner().invoke(main, ["setup"], input="n\nn\nn\nn\nn\n")

    assert result.exit_code == 0, result.output
    assert "Could not list devices: session expired" in result.output
    assert "Setup complete." in result.output


def test_a_short_pin_aborts_only_the_app_lock_step(
    tmp_db, two_devices, stub_auth: list[str]
) -> None:
    result = CliRunner().invoke(main, ["setup"], input="n\nn\nall\nn\nn\ny\n12\n12\n")

    assert result.exit_code == 0, result.output
    assert "PIN must be at least" in result.output
    assert "Setup complete." in result.output

    with session_scope() as session:
        assert load_settings(session).pin_configured is False


def test_an_accepted_pin_turns_the_lock_on(tmp_db, two_devices, stub_auth: list[str]) -> None:
    result = CliRunner().invoke(main, ["setup"], input="n\nn\nall\nn\nn\ny\n864213\n864213\n")

    assert result.exit_code == 0, result.output
    assert "Locking does not encrypt the database." in result.output

    with session_scope() as session:
        settings = load_settings(session)
        assert settings.pin_configured is True
        assert settings.lock_enabled is True
