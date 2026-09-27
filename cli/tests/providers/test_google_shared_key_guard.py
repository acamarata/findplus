"""Part 1 safety: the vendored key/browser paths never run on their own.

Purpose    : After a sign-in nothing installs Find+'s isolated driver, so a
             poll's decrypt could otherwise reach the vendor's create_driver
             (which runs `pkill -f chrome`) or its shared-key retrieval (which
             calls input()). install_vendor_guards() replaces both with typed
             raisers, so a locked account surfaces `needs: shared_key`, never a
             crash, a stdin block, or a killed Chrome.
Constraints: No browser, no os.system/subprocess launch, no real ~/.findplus.
"""

from __future__ import annotations

import json

import pytest

from findplus.providers.google_findhub.bootstrap import (
    ensure_gfmt_importable,
    has_shared_key,
    install_vendor_guards,
    needs_shared_key,
)
from findplus.providers.google_findhub.types import (
    BrowserLaunchBlockedError,
    SharedKeyRequiredError,
)

SESSION = {"aas_token": "aas_et/x", "username": "kid@example.com"}


def _sign_in(tmp_db, extra: dict | None = None) -> None:
    from findplus.config import get_settings

    settings = get_settings()
    settings.ensure_dirs()
    settings.secrets_file.write_text(json.dumps({**SESSION, **(extra or {})}))


def test_create_driver_is_blocked_and_kills_nothing(tmp_db, monkeypatch) -> None:
    """The vendor's create_driver would `pkill -f chrome`; the guard raises first."""
    import os
    import subprocess

    ensure_gfmt_importable()
    install_vendor_guards()

    killed: list = []
    monkeypatch.setattr(os, "system", lambda cmd: killed.append(cmd))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: killed.append(a))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: killed.append(a))

    import chrome_driver

    with pytest.raises(BrowserLaunchBlockedError):
        chrome_driver.create_driver()
    assert killed == []  # nothing was killed and no browser was spawned


def test_shared_key_retrieval_never_blocks_on_stdin_or_opens_a_browser(tmp_db, monkeypatch) -> None:
    _sign_in(tmp_db)
    ensure_gfmt_importable()
    install_vendor_guards()

    import builtins

    monkeypatch.setattr(builtins, "input", lambda *a, **k: pytest.fail("input() was called"))

    import KeyBackup.shared_key_retrieval as skr

    with pytest.raises(SharedKeyRequiredError):
        skr.get_shared_key()


def test_needs_shared_key_reflects_the_store(tmp_db) -> None:
    _sign_in(tmp_db)
    assert needs_shared_key() is True and has_shared_key() is False
    _sign_in(tmp_db, {"shared_key": "abcd"})
    assert needs_shared_key() is False and has_shared_key() is True
    _sign_in(tmp_db, {"owner_key": "ffff"})
    assert needs_shared_key() is False  # the derived owner key counts as unlocked


def test_a_signed_out_account_never_needs_a_shared_key(tmp_db) -> None:
    assert needs_shared_key() is False  # no session at all


def test_locate_raises_the_typed_needs_unlock_error_before_any_network(tmp_db, monkeypatch) -> None:
    """client.locate() must fail with SharedKeyRequiredError, not make a Nova
    request whose payload could not be decrypted."""
    _sign_in(tmp_db)
    from findplus.providers.google_findhub.client import FindHubClient

    def _boom(*a, **k):
        raise AssertionError("a network request was made before the unlock check")

    monkeypatch.setattr(
        "findplus.providers.google_findhub.client.FindHubClient.list_devices", _boom, raising=False
    )
    with pytest.raises(SharedKeyRequiredError):
        FindHubClient().locate("TAG-1", "Tag")


def test_the_poller_reports_needs_shared_key(tmp_db, monkeypatch, register_provider) -> None:
    """A locked account makes the poll report `needs_shared_key`, never crash."""
    from findplus.poller import _locate

    class LockedProvider:
        def locate(self, device_id, name):
            raise SharedKeyRequiredError("locked")

    outcome, observations = _locate(LockedProvider(), "TAG-1", "Tag")
    assert observations is None
    assert outcome.status == "needs_shared_key"
    assert outcome.error_type == "SharedKeyRequiredError"


def test_auth_status_lists_shared_key_in_needs_when_locked(tmp_db, monkeypatch) -> None:
    _sign_in(tmp_db)
    monkeypatch.setattr(
        "findplus.cli.doctor.check_chrome",
        lambda: __import__("findplus.cli.doctor", fromlist=["DoctorCheck"]).DoctorCheck(
            "chrome", "Chrome", True, "found"
        ),
    )
    from findplus.providers.auth_status import build_auth_status

    google = next(row for row in build_auth_status()["providers"] if row["id"] == "google-find-hub")
    assert google["signed_in"] is True
    assert "shared_key" in google["needs"]
