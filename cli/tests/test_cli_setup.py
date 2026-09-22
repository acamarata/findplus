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
    # _discover_devices() (blind B2) gates each provider on is_authenticated();
    # a fresh tmp_db has no real secrets.json, so Google must be stubbed signed
    # in too, matching the real flow where _step_signin runs first.
    monkeypatch.setattr(
        "findplus.providers.google_findhub.client.FindHubClient.is_authenticated",
        lambda self: True,
    )
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
    # R-P2-24: --yes never stamps completed_at, only last_step = "headless",
    # so install.sh --start leaves the web first-run wizard armed.
    assert _completed_at() is None

    with session_scope() as session:
        assert get_setting(session, "onboarding.last_step") == "headless"
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


def test_yes_never_stamps_completed_at(tmp_db) -> None:
    """R-P2-24: repeated --yes runs stay headless; completed_at never gets set."""
    first = CliRunner().invoke(main, ["setup", "--yes"])
    second = CliRunner().invoke(main, ["setup", "--yes"])

    assert (first.exit_code, second.exit_code) == (0, 0), second.output
    assert _completed_at() is None
    with session_scope() as session:
        assert get_setting(session, "onboarding.last_step") == "headless"


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
        "findplus.providers.google_findhub.client.FindHubClient.is_authenticated",
        lambda self: True,
    )
    monkeypatch.setattr(
        "findplus.providers.google_findhub.client.FindHubClient.list_devices", _raise
    )

    result = CliRunner().invoke(main, ["setup"], input="n\nn\nn\nn\nn\n")

    assert result.exit_code == 0, result.output
    assert "Could not list devices: session expired" in result.output
    assert "Setup complete." in result.output


class _FakeRegistryProvider:
    """A LocationProvider fake keyed by registry name, for _discover_devices()
    tests that need to control is_available/is_authenticated per provider."""

    def __init__(self, name: str, display_name: str, devices=()) -> None:
        self.name = name
        self.display_name = display_name
        self._devices = list(devices)

    def is_available(self):
        return True, ""

    def is_authenticated(self):
        return True

    def list_devices(self):
        return list(self._devices)


def test_interactive_devices_step_lists_both_providers(
    tmp_db, stub_auth: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blind B2: an Apple Find My accessory must appear alongside a Google
    device, not just Google's -- the wizard iterates the provider registry
    the same way routes_devices.py's dashboard refresh does."""
    from findplus.providers.base import ProviderDevice

    providers = {
        "google-find-hub": _FakeRegistryProvider(
            "google-find-hub",
            "Google Find Hub",
            devices=[ProviderDevice("google-find-hub", "TAG-1", "Alpha", None, {})],
        ),
        "apple-find-my": _FakeRegistryProvider(
            "apple-find-my",
            "Apple Find My",
            devices=[ProviderDevice("apple-find-my", "ACC-1", "Keys", "tag", {})],
        ),
    }
    monkeypatch.setattr(
        "findplus.providers.base.available_providers", lambda: list(providers), raising=False
    )
    monkeypatch.setattr(
        "findplus.providers.base.get_provider", lambda n: providers[n], raising=False
    )

    result = CliRunner().invoke(main, ["setup"], input="n\nn\nall\nn\nn\nn\n")

    assert result.exit_code == 0, result.output
    assert "Alpha (TAG-1) [Google Find Hub]" in result.output
    assert "Keys (ACC-1) [Apple Find My]" in result.output
    with session_scope() as session:
        tracked = {d.device_id for d in get_tracked_devices(session)}
    assert tracked == {"TAG-1", "ACC-1"}


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


def test_declined_sign_in_leaves_setup_unfinished(tmp_db) -> None:
    """UAT U18: no provider fixture, so declining both offers is a genuine
    unauthenticated run. The devices step says so instead of "No devices
    found", the closing message says so instead of "Setup complete", and
    completed_at is never stamped -- the web wizard stays offered."""
    result = CliRunner().invoke(main, ["setup"], input="n\nn\nn\nn\nn\n")

    assert result.exit_code == 0, result.output
    assert "Not signed in yet. Run `findplus auth` to connect a provider first." in result.output
    assert "Setup complete." not in result.output
    assert "Not signed in yet. Run `findplus auth` when you're ready" in result.output

    assert _completed_at() is None
    with session_scope() as session:
        assert get_setting(session, "onboarding.last_step") == "signin"


def test_interactive_done_stamps_and_restamps_completed_at(
    tmp_db, two_devices, stub_auth: list[str]
) -> None:
    """Only the interactive wizard's Done step writes completed_at (R-P2-24);
    a second run re-stamps it, unlike --yes which never touches it."""
    first = CliRunner().invoke(main, ["setup"], input="n\nn\nall\nn\nn\nn\n")
    stamped_first = _completed_at()

    second = CliRunner().invoke(main, ["setup"], input="n\nn\nall\nn\nn\nn\n")

    assert (first.exit_code, second.exit_code) == (0, 0), second.output
    assert stamped_first is not None
    assert _completed_at() > stamped_first
