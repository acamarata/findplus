"""The Find+-owned shared-key flow always stops: cancel, deadline, browser errors.

Purpose    : Regression for the unlock thread that spun a CPU core forever once the
             Chrome window closed (the vendored loop swallowed every exception).
Constraints: Fake drivers only; no browser, no network, no real ~/.findplus.
"""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest
from selenium.common.exceptions import NoAlertPresentException, NoSuchWindowException

from findplus.providers.google_findhub import unlock, unlock_flow
from tests.providers._google_token_helpers import isolate_store


class _Switch:
    def __init__(self, driver: _Driver) -> None:
        self._d = driver

    @property
    def alert(self):
        self._d.alert_reads += 1
        if self._d.closed:
            raise NoSuchWindowException("window gone")
        if self._d.alerts:
            text = self._d.alerts.pop(0)
            return SimpleNamespace(text=text, accept=lambda: None)
        raise NoAlertPresentException()


class _Driver:
    def __init__(self, alerts: list[str] | None = None) -> None:
        self.alerts = alerts or []
        self.closed = False
        self.alert_reads = 0
        self.quit_calls = 0
        self.current_url = "https://myaccount.google.com/"
        self.switch_to = _Switch(self)

    def get(self, _url: str) -> None:
        pass

    def execute_script(self, _script: str) -> None:
        pass

    def quit(self) -> None:
        self.quit_calls += 1


def _run(driver: _Driver, cancelled=lambda: False, sleep=lambda _s: None):
    return unlock_flow.run_shared_key_flow(lambda: driver, cancelled, sleep=sleep)


def test_a_closed_window_ends_the_flow_instead_of_spinning(tmp_db) -> None:
    driver = _Driver()
    driver.closed = True
    with pytest.raises(NoSuchWindowException):
        _run(driver)
    assert driver.alert_reads == 1
    assert driver.quit_calls == 1


def test_cancel_stops_the_wait_loop(tmp_db) -> None:
    driver = _Driver()
    flag = {"n": 0}

    def cancelled() -> bool:
        flag["n"] += 1
        return flag["n"] > 3

    with pytest.raises(unlock_flow.FlowCancelledError):
        _run(driver, cancelled)
    assert driver.quit_calls == 1


def test_the_deadline_ends_a_wait_with_no_alert(tmp_db, monkeypatch) -> None:
    monkeypatch.setattr(unlock_flow, "_TOTAL_SECONDS", 0.05)
    with pytest.raises(unlock_flow.FlowTimeoutError):
        _run(_Driver(), sleep=lambda _s: time.sleep(0.02))


def test_close_view_returns_none_and_quits(tmp_db) -> None:
    driver = _Driver([json.dumps({"method": "closeView"})])
    assert _run(driver) is None
    assert driver.quit_calls == 1


def test_a_key_alert_returns_the_hex(tmp_db, monkeypatch) -> None:
    import KeyBackup.response_parser as parser

    unlock_flow.ensure_gfmt_importable()
    monkeypatch.setattr(parser, "get_fmdn_shared_key", lambda _v: bytes.fromhex("abcd"))
    msg = json.dumps({"method": "setVaultSharedKeys", "vaultKeys": "x"})
    assert _run(_Driver([msg])) == "abcd"


def test_cancelling_an_unlock_really_ends_its_thread(tmp_db, monkeypatch) -> None:
    isolate_store(monkeypatch)
    unlock._jobs.clear()
    unlock._active_job_id = None
    driver = _Driver()
    monkeypatch.setattr(unlock, "_make_isolated_driver", lambda _s, _j: lambda: driver)
    from findplus.config import get_settings

    before = set(threading.enumerate())
    job_id = unlock.start_google_unlock(get_settings())
    time.sleep(0.2)
    assert unlock.cancel_google_unlock(job_id) is True
    deadline = time.monotonic() + 3
    extra: list[threading.Thread] = []
    while time.monotonic() < deadline:
        extra = [t for t in threading.enumerate() if t not in before and t.is_alive()]
        if not extra:
            break
        time.sleep(0.05)
    assert not extra, "the unlock thread is still running after cancel"
    assert driver.quit_calls >= 1


def test_every_vendor_module_gets_the_guard_back(tmp_db) -> None:
    from findplus.providers.google_findhub import bootstrap

    bootstrap.ensure_gfmt_importable()
    bootstrap.set_create_driver(lambda: "real")
    import Auth.auth_flow as auth_flow
    import chrome_driver
    import KeyBackup.shared_key_flow as shared_key_flow

    assert auth_flow.create_driver() == "real"
    bootstrap.restore_create_driver_guard()
    for mod in (chrome_driver, auth_flow, shared_key_flow):
        assert mod.create_driver is bootstrap._blocked_create_driver
