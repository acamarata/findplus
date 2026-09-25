"""Apple Find My auth: session save/restore, 2FA, and file-mode invariants.

FakeAppleAccount is a real findmy.AsyncAppleAccount subclass with only Apple's
servers replaced (tests/providers/_fake_findmy.py), so these tests exercise the
installed library's state machine, 2FA method objects and to_json/from_json.
Every test uses tmp_path for settings.state_dir; never ~/.findplus.
"""

from __future__ import annotations

import json

import pytest

findmy = pytest.importorskip("findmy")

from findplus.config import get_settings  # noqa: E402
from findplus.providers.apple_findmy import auth as auth_mod  # noqa: E402
from findplus.providers.apple_findmy.exceptions import AppleAuthRequiredError  # noqa: E402
from findplus.providers.apple_findmy.session import (  # noqa: E402
    AppleAnisetteError,
    AppleSession,
)
from tests.providers._fake_findmy import GOOD_CODE, FakeAppleAccount  # noqa: E402

SECRET = "hunter2-never-on-disk"


def _settings(tmp_path):
    return get_settings(state_dir=tmp_path)


def _signed_in(tmp_path) -> FakeAppleAccount:
    account = FakeAppleAccount()
    with AppleSession(account) as session:
        session.run(account.login("appleid@example.com", SECRET))
    auth_mod.save_account(account, _settings(tmp_path))
    return account


def test_save_and_restore_round_trip(tmp_path) -> None:
    _signed_in(tmp_path)
    restored = auth_mod.restore_account(_settings(tmp_path))
    assert isinstance(restored, findmy.AsyncAppleAccount)
    assert restored.login_state == findmy.LoginState.LOGGED_IN
    assert restored.account_name == "appleid@example.com"


def test_the_password_is_never_written(tmp_path) -> None:
    """FindMy.py's to_json() includes the password; the saved file must not."""
    _signed_in(tmp_path)
    text = (tmp_path / "apple-account.json").read_text(encoding="utf-8")
    assert SECRET not in text
    assert json.loads(text)["account"]["password"] is None


def test_restore_missing_file(tmp_path) -> None:
    with pytest.raises(AppleAuthRequiredError, match="findplus auth"):
        auth_mod.restore_account(_settings(tmp_path))


def test_restore_unfinished_sign_in(tmp_path) -> None:
    """A session saved mid-2FA never counts as signed in."""
    account = FakeAppleAccount(requires_2fa_val=True)
    with AppleSession(account) as session:
        session.run(account.login("a@b.com", SECRET))
    auth_mod.save_account(account, _settings(tmp_path))
    with pytest.raises(AppleAuthRequiredError, match="Apple session expired"):
        auth_mod.restore_account(_settings(tmp_path))


def test_restore_corrupt_file(tmp_path) -> None:
    (tmp_path / "apple-account.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(AppleAuthRequiredError, match="Apple session expired"):
        auth_mod.restore_account(_settings(tmp_path))


def _prompts(monkeypatch, answers: list[str]) -> None:
    it = iter(answers)
    monkeypatch.setattr(auth_mod.click, "prompt", lambda *a, **k: next(it))


def test_2fa_trusted_device(tmp_path, monkeypatch) -> None:
    account = FakeAppleAccount(requires_2fa_val=True)
    monkeypatch.setattr(auth_mod, "make_account", lambda s: account)
    _prompts(monkeypatch, ["appleid@example.com", SECRET, "1", GOOD_CODE])
    assert auth_mod.sign_in_interactive(_settings(tmp_path)) is account
    assert account.requests == ["trusted_device"]
    assert auth_mod.is_signed_in(auth_mod.read_saved_state(_settings(tmp_path)))


def test_2fa_sms_choice(tmp_path, monkeypatch, capsys) -> None:
    account = FakeAppleAccount(requires_2fa_val=True)
    monkeypatch.setattr(auth_mod, "make_account", lambda s: account)
    _prompts(monkeypatch, ["appleid@example.com", SECRET, "2", GOOD_CODE])
    auth_mod.sign_in_interactive(_settings(tmp_path))
    assert account.requests == ["sms:7"]
    assert "SMS to" in capsys.readouterr().out


def test_wrong_code_is_not_saved(tmp_path, monkeypatch) -> None:
    account = FakeAppleAccount(requires_2fa_val=True)
    monkeypatch.setattr(auth_mod, "make_account", lambda s: account)
    _prompts(monkeypatch, ["appleid@example.com", SECRET, "1", "000000"])
    with pytest.raises(findmy.UnhandledProtocolError):
        auth_mod.sign_in_interactive(_settings(tmp_path))
    assert not (tmp_path / "apple-account.json").exists()


@pytest.mark.posix_only
def test_file_mode_0600(tmp_path) -> None:
    _signed_in(tmp_path)
    assert (tmp_path / "apple-account.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.posix_only
def test_resave_narrows_a_wide_mode_before_writing(tmp_path) -> None:
    """E11 review: the file is chmodded 0600 before the session token is written,
    so a re-save over a world-readable file never exposes the token."""
    account = _signed_in(tmp_path)
    path = tmp_path / "apple-account.json"
    path.chmod(0o644)
    auth_mod.save_account(account, _settings(tmp_path))
    assert path.stat().st_mode & 0o777 == 0o600


def test_login_failure_propagates_unwrapped(tmp_path, monkeypatch) -> None:
    """QA-B boundary: a login() failure is not wrapped in AppleAuthRequiredError."""
    account = FakeAppleAccount()
    account.login_error = findmy.InvalidCredentialsError("Password authentication failed")
    monkeypatch.setattr(auth_mod, "make_account", lambda s: account)
    _prompts(monkeypatch, ["x", "x"])
    with pytest.raises(findmy.InvalidCredentialsError, match="Password authentication failed"):
        auth_mod.sign_in_interactive(_settings(tmp_path))


def test_anisette_failure_is_named_before_any_login(tmp_path, monkeypatch) -> None:
    """A local anisette that cannot download its libraries says so, not 'bad password'."""

    class NoAnisette(FakeAppleAccount):
        async def get_anisette_headers(self, with_client_info=False, serial="0"):
            raise OSError("network unreachable")

    account = NoAnisette()
    monkeypatch.setattr(auth_mod, "make_account", lambda s: account)
    _prompts(monkeypatch, ["x", "x"])
    with pytest.raises(AppleAnisetteError, match=r"anisette\.dl\.mikealmel\.ooo") as excinfo:
        auth_mod.sign_in_interactive(_settings(tmp_path))
    assert "APPLE_ANISETTE_URL" in str(excinfo.value)
    assert account.logged_in_as is None
