"""Disconnect cancels a running sign-in/unlock job; a late job stores nothing (r1 review #7)."""

from __future__ import annotations

import json
import threading
import time

import pytest

from findplus.config import get_settings
from findplus.providers import signout
from findplus.providers.google_findhub import browser, helper_state, unlock, unlock_flow
from tests.providers._google_token_helpers import isolate_store


@pytest.fixture(autouse=True)
def _clean():
    for mod in (unlock, browser):
        mod._jobs.clear()
        mod._active_job_id = None
    helper_state.reset_for_tests()
    yield
    for mod in (unlock, browser):
        mod._jobs.clear()
        mod._active_job_id = None
    helper_state.reset_for_tests()


def _wait(pred, timeout=3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_disconnect_cancels_unlock_and_the_late_key_is_not_stored(tmp_db, monkeypatch) -> None:
    store = isolate_store(monkeypatch)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps({"aas_token": "x", "username": "a@b.com"}))
    release = threading.Event()

    def flow(*_a, **_k):
        release.wait(3)
        return "deadbeef"

    monkeypatch.setattr(unlock_flow, "run_shared_key_flow", flow)
    monkeypatch.setattr(unlock, "_wake_poller", lambda: None)
    job_id = unlock.start_google_unlock(get_settings())
    token = helper_state.create_state(helper_state.KIND_UNLOCK)

    signout.sign_out(signout.GOOGLE, get_settings())
    release.set()  # the flow now returns a key for the account that just signed out

    assert _wait(lambda: unlock._jobs[job_id].get("cancelled"))
    time.sleep(0.2)
    assert not store.exists() or "shared_key" not in json.loads(store.read_text() or "{}")
    assert unlock.get_google_unlock_progress(job_id)["message"] == unlock.MSG_CANCELLED
    assert helper_state.consume_state(helper_state.KIND_UNLOCK, token) is False


def test_a_key_is_refused_when_no_account_is_signed_in(tmp_db, monkeypatch) -> None:
    store = isolate_store(monkeypatch)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("{}")
    with pytest.raises(unlock.SharedKeyParseError, match="not signed in"):
        unlock._store_shared_key("deadbeef")
    assert "shared_key" not in json.loads(store.read_text())


def test_disconnect_cancels_a_running_own_window_signin(tmp_db, monkeypatch) -> None:
    isolate_store(monkeypatch)
    started = threading.Event()
    release = threading.Event()
    settings = get_settings()
    settings.ensure_dirs()

    class _Client:
        def __init__(self, _settings) -> None:
            pass

        def authenticate(self) -> str:
            started.set()
            release.wait(3)
            settings.secrets_file.write_text(json.dumps({"aas_token": "late"}))
            return "a@b.com"

    import findplus.providers.google_findhub.client as client_mod

    monkeypatch.setattr(client_mod, "FindHubClient", _Client)
    monkeypatch.setattr(browser, "_patch_vendor_chrome", lambda *_a: None)
    from findplus.cli import doctor

    class _Ok:
        passed = True

    monkeypatch.setattr(doctor, "check_chrome", lambda: _Ok())
    job_id = browser.start_google_auth(settings)
    assert started.wait(3)

    signout.sign_out(signout.GOOGLE, settings)
    release.set()

    assert _wait(lambda: not settings.secrets_file.exists() and threading.active_count() >= 1)
    time.sleep(0.3)
    assert not settings.secrets_file.exists()
    assert browser.get_google_auth_progress(job_id)["message"] == browser.MSG_CANCELLED
