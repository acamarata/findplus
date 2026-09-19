"""Apple Find My auth: session save/restore, 2FA, and file-mode invariants.

FakeAccount/FakeMethod stand in for findmy.AppleAccount so these tests never
import findmy or touch the network. Every test uses tmp_path for
settings.state_dir; never ~/.findplus.
"""

from __future__ import annotations

import pytest

from findplus.config import get_settings
from findplus.providers.apple_findmy import auth as auth_mod
from findplus.providers.apple_findmy.exceptions import AppleAuthRequiredError


class FakeMethod:
    def __init__(self, name: str) -> None:
        self._name = name

    def request(self) -> None:
        pass

    def submit(self, code: str) -> None:
        pass


class FakeAccount:
    def __init__(self, requires_2fa_val: bool = False) -> None:
        self.requires_2fa_val = requires_2fa_val
        self.logged_in_as: tuple[str, str] | None = None

    def login(self, apple_id: str, password: str) -> None:
        self.logged_in_as = (apple_id, password)

    def requires_2fa(self) -> bool:
        return self.requires_2fa_val

    def get_2fa_methods(self) -> list:
        return [FakeMethod("trusted_device")]

    def to_json(self) -> dict:
        return {"token": "fake"}

    def restore_session(self, data: dict) -> None:
        pass


def _settings(tmp_path):
    return get_settings(state_dir=tmp_path)


def test_save_and_restore(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(auth_mod, "make_account", lambda s: FakeAccount())
    account = auth_mod.make_account(settings)
    auth_mod.save_account(account, settings)
    assert (tmp_path / "apple-account.json").exists()
    restored = auth_mod.restore_account(settings)
    assert isinstance(restored, FakeAccount)


def test_restore_missing_file(tmp_path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(AppleAuthRequiredError, match="findplus auth"):
        auth_mod.restore_account(settings)


def test_restore_expired_session(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(auth_mod, "make_account", lambda s: FakeAccount())
    auth_mod.save_account(FakeAccount(), settings)

    class ExpiredAccount(FakeAccount):
        def restore_session(self, data: dict) -> None:
            raise Exception("expired")

    monkeypatch.setattr(auth_mod, "make_account", lambda s: ExpiredAccount())
    with pytest.raises(AppleAuthRequiredError, match="Apple session expired"):
        auth_mod.restore_account(settings)


def test_2fa_trusted_device(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(auth_mod, "make_account", lambda s: FakeAccount(requires_2fa_val=True))
    prompts = iter(["appleid@example.com", "hunter2", "1", "123456"])
    monkeypatch.setattr(auth_mod.click, "prompt", lambda *a, **k: next(prompts))
    account = auth_mod.sign_in_interactive(settings)
    assert isinstance(account, FakeAccount)
    assert (tmp_path / "apple-account.json").exists()


@pytest.mark.posix_only
def test_file_mode_0600(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(auth_mod, "make_account", lambda s: FakeAccount())
    account = auth_mod.make_account(settings)
    auth_mod.save_account(account, settings)
    mode = (tmp_path / "apple-account.json").stat().st_mode & 0o777
    assert mode == 0o600


@pytest.mark.posix_only
def test_resave_narrows_a_wide_mode_before_writing(tmp_path, monkeypatch) -> None:
    """E11 review: the file is chmodded 0600 before the session token is written,
    so a re-save over a world-readable file never exposes the token."""
    settings = _settings(tmp_path)
    monkeypatch.setattr(auth_mod, "make_account", lambda s: FakeAccount())
    auth_mod.save_account(FakeAccount(), settings)
    path = tmp_path / "apple-account.json"
    path.chmod(0o644)
    auth_mod.save_account(FakeAccount(), settings)
    assert path.stat().st_mode & 0o777 == 0o600


def test_login_failure_propagates_unwrapped(tmp_path, monkeypatch) -> None:
    """QA-B boundary: a login() failure is not wrapped in AppleAuthRequiredError
    (only restore_session() failures are, since login() has an interactive user
    to show the raw error to)."""
    settings = _settings(tmp_path)

    class BadCredsAccount(FakeAccount):
        def login(self, apple_id: str, password: str) -> None:
            raise Exception("bad credentials")

    monkeypatch.setattr(auth_mod, "make_account", lambda s: BadCredsAccount())
    monkeypatch.setattr(auth_mod.click, "prompt", lambda *a, **k: "x")
    with pytest.raises(Exception, match="bad credentials"):
        auth_mod.sign_in_interactive(settings)
