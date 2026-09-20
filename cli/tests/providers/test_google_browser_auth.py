"""The isolated Chrome sign-in wrapper: no pkill, own profile, job state machine.

Every case here uses FakeDriver (the same shape test_apple_auth.py's FakeAccount
has) and never reaches a real browser, a real vendor import, or a socket. The
two things that would be genuinely dangerous to exercise for real -- the vendor
patch and `uc.Chrome()` -- are monkeypatched in every test that touches them.
"""

from __future__ import annotations

import os
import time

import pytest

from findplus.config import get_settings
from findplus.providers.google_findhub import browser


class FakeDriver:
    """Stands in for an undetected_chromedriver.Chrome instance."""

    def __init__(self, cookies: dict | None = None, **kwargs) -> None:
        self.kwargs = kwargs
        self.cookies = cookies or {}
        self.quit_calls = 0

    def get_cookie(self, name: str):
        return self.cookies.get(name)

    def quit(self) -> None:
        self.quit_calls += 1


@pytest.fixture(autouse=True)
def _clean_jobs():
    """`_jobs`/`_active_job_id` live for the process, so reset them per test."""
    browser._jobs.clear()
    browser._active_job_id = None
    yield
    browser._jobs.clear()
    browser._active_job_id = None


def _waiting() -> dict:
    return {"state": "waiting_for_user", "message": "", "finished_monotonic": None}


def _chrome(passed: bool):
    from findplus.cli.doctor import DoctorCheck

    return lambda: DoctorCheck("chrome", "Google Chrome", passed, "fake")


# ------------------------------------------------------------ the vendor patch
def test_patch_replaces_create_driver_and_input(tmp_path, monkeypatch) -> None:
    import sys
    import types

    vendor_chrome = types.ModuleType("chrome_driver")
    vendor_chrome.create_driver = lambda: "original"
    vendor_chrome.get_options = lambda: "options"
    auth_flow = types.ModuleType("Auth.auth_flow")
    auth_flow.input = input
    auth_pkg = types.ModuleType("Auth")
    auth_pkg.auth_flow = auth_flow
    monkeypatch.setitem(sys.modules, "chrome_driver", vendor_chrome)
    monkeypatch.setitem(sys.modules, "Auth", auth_pkg)
    monkeypatch.setitem(sys.modules, "Auth.auth_flow", auth_flow)
    monkeypatch.setattr(browser, "ensure_gfmt_importable", lambda: tmp_path)

    browser._patch_vendor_chrome(get_settings(state_dir=tmp_path), "job-1")

    # Not called here: calling it would build a real Chrome. That path has its
    # own test below, with uc.Chrome faked.
    assert vendor_chrome.create_driver.__name__ == "_isolated_create_driver"
    assert auth_flow.input("[AuthFlow] Press Enter to continue...") == ""


def _patched_create_driver(tmp_path, monkeypatch, made: list):
    """Install the patch against fake vendor modules; return create_driver."""
    import sys
    import types

    import undetected_chromedriver as uc

    def fake_chrome(**kwargs):
        driver = FakeDriver(**kwargs)
        made.append(driver)
        return driver

    monkeypatch.setattr(uc, "Chrome", fake_chrome)
    vendor_chrome = types.ModuleType("chrome_driver")
    vendor_chrome.create_driver = lambda: "original"
    vendor_chrome.get_options = lambda: "options"
    auth_flow = types.ModuleType("Auth.auth_flow")
    auth_flow.input = input
    auth_pkg = types.ModuleType("Auth")
    auth_pkg.auth_flow = auth_flow
    monkeypatch.setitem(sys.modules, "chrome_driver", vendor_chrome)
    monkeypatch.setitem(sys.modules, "Auth", auth_pkg)
    monkeypatch.setitem(sys.modules, "Auth.auth_flow", auth_flow)
    monkeypatch.setattr(browser, "ensure_gfmt_importable", lambda: tmp_path)
    settings = get_settings(state_dir=tmp_path)
    browser._jobs["job-2"] = {"state": "launching", "message": "", "finished_monotonic": None}
    browser._patch_vendor_chrome(settings, "job-2")
    return vendor_chrome.create_driver, settings


@pytest.mark.posix_only
def test_isolated_driver_never_kills_chrome_and_owns_its_profile(tmp_path, monkeypatch) -> None:
    """The whole point of the wrapper: the user's own Chrome is left alone."""

    def explode(command):  # pragma: no cover - the assertion is that it never runs
        raise AssertionError(f"os.system called: {command!r}")

    monkeypatch.setattr(os, "system", explode)
    made: list[FakeDriver] = []
    create_driver, settings = _patched_create_driver(tmp_path, monkeypatch, made)

    proxy = create_driver()

    assert made[0].kwargs["user_data_dir"] == str(settings.chrome_profile_dir)
    assert made[0].kwargs["version_main"] is None
    assert settings.chrome_profile_dir.is_dir()
    assert os.stat(settings.chrome_profile_dir).st_mode & 0o777 == 0o700
    assert browser._jobs["job-2"]["state"] == "waiting_for_user"
    assert isinstance(proxy, browser._CookieWatchProxy)


def test_profile_dir_is_narrowed_even_when_it_already_exists(tmp_path, monkeypatch) -> None:
    """mkdir(mode=) does nothing to an existing directory; the chmod does."""
    settings = get_settings(state_dir=tmp_path)
    settings.chrome_profile_dir.mkdir(parents=True)
    os.chmod(settings.chrome_profile_dir, 0o755)
    made: list[FakeDriver] = []
    create_driver, _ = _patched_create_driver(tmp_path, monkeypatch, made)

    create_driver()

    if os.name != "nt":
        assert os.stat(settings.chrome_profile_dir).st_mode & 0o777 == 0o700


# --------------------------------------------------------- the cookie observer
def test_cookie_proxy_flips_to_capturing_only_for_a_real_oauth_token() -> None:
    driver = FakeDriver(cookies={"oauth_token": {"value": "t"}})
    browser._jobs["job-3"] = _waiting()
    proxy = browser._CookieWatchProxy(driver, "job-3")

    assert proxy.get_cookie("something_else") is None
    assert browser._jobs["job-3"]["state"] == "waiting_for_user"

    empty = FakeDriver(cookies={})
    browser._jobs["job-4"] = _waiting()
    assert browser._CookieWatchProxy(empty, "job-4").get_cookie("oauth_token") is None
    assert browser._jobs["job-4"]["state"] == "waiting_for_user"

    assert proxy.get_cookie("oauth_token") == {"value": "t"}
    assert browser._jobs["job-3"]["state"] == "capturing"


def test_cookie_proxy_delegates_quit_through_getattr() -> None:
    driver = FakeDriver()
    proxy = browser._CookieWatchProxy(driver, "job-5")
    proxy.quit()
    assert driver.quit_calls == 1


# ------------------------------------------------------------ start / progress
def test_start_raises_when_chrome_is_missing_and_starts_no_thread(tmp_path, monkeypatch) -> None:
    from findplus.cli import doctor

    monkeypatch.setattr(doctor, "check_chrome", _chrome(False))
    monkeypatch.setattr(
        browser.threading,
        "Thread",
        lambda *a, **k: pytest.fail("a thread was started despite a missing Chrome"),
    )

    with pytest.raises(browser.ChromeNotFoundError) as excinfo:
        browser.start_google_auth(get_settings(state_dir=tmp_path))

    assert str(excinfo.value) == browser.MSG_CHROME_MISSING
    assert browser._jobs == {}


def test_a_second_concurrent_start_reports_the_first_job_id(tmp_path, monkeypatch) -> None:
    from findplus.cli import doctor

    monkeypatch.setattr(doctor, "check_chrome", _chrome(True))
    monkeypatch.setattr(browser, "_run_google_auth", lambda job_id, settings: None)
    settings = get_settings(state_dir=tmp_path)

    first = browser.start_google_auth(settings)

    with pytest.raises(browser.GoogleAuthAlreadyRunningError) as excinfo:
        browser.start_google_auth(settings)
    assert excinfo.value.job_id == first


def test_a_full_lifecycle_reaches_done(tmp_path, monkeypatch) -> None:
    from findplus.cli import doctor
    from findplus.providers.google_findhub import client as client_mod

    monkeypatch.setattr(doctor, "check_chrome", _chrome(True))
    monkeypatch.setattr(browser, "_patch_vendor_chrome", lambda settings, job_id: None)

    class FakeClient:
        def __init__(self, settings) -> None:
            pass

        def authenticate(self) -> str:
            return "a@b.com"

    monkeypatch.setattr(client_mod, "FindHubClient", FakeClient)

    job_id = browser.start_google_auth(get_settings(state_dir=tmp_path))
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        progress = browser.get_google_auth_progress(job_id)
        if progress["state"] in ("done", "failed"):
            break
        time.sleep(0.01)

    assert progress == {"state": "done", "message": "Authenticated as a@b.com."}


def test_a_selenium_timeout_becomes_the_friendly_message(tmp_path, monkeypatch) -> None:
    from selenium.common.exceptions import TimeoutException

    from findplus.cli import doctor
    from findplus.providers.google_findhub import client as client_mod

    monkeypatch.setattr(doctor, "check_chrome", _chrome(True))
    monkeypatch.setattr(browser, "_patch_vendor_chrome", lambda settings, job_id: None)

    class TimingOutClient:
        def __init__(self, settings) -> None:
            pass

        def authenticate(self) -> str:
            raise TimeoutException("Message: \n")

    monkeypatch.setattr(client_mod, "FindHubClient", TimingOutClient)

    job_id = browser.start_google_auth(get_settings(state_dir=tmp_path))
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        progress = browser.get_google_auth_progress(job_id)
        if progress["state"] in ("done", "failed"):
            break
        time.sleep(0.01)

    assert progress == {"state": "failed", "message": browser.MSG_TIMEOUT}


def test_an_unknown_job_id_returns_none() -> None:
    assert browser.get_google_auth_progress("no-such-job") is None


def test_a_finished_job_is_swept_after_the_ttl(monkeypatch) -> None:
    browser._jobs["old"] = {"state": "done", "message": "x", "finished_monotonic": 100.0}
    browser._active_job_id = "old"

    monkeypatch.setattr(browser.time, "monotonic", lambda: 100.0 + browser._JOB_TTL_SECONDS - 1)
    assert browser.get_google_auth_progress("old") is not None

    monkeypatch.setattr(browser.time, "monotonic", lambda: 100.0 + browser._JOB_TTL_SECONDS + 1)
    assert browser.get_google_auth_progress("old") is None
    assert browser._active_job_id is None


def test_a_stalled_job_is_swept_so_a_hung_launch_cannot_block_every_retry(monkeypatch) -> None:
    """CR-C-E6 F2: a job that never reaches a terminal state has no
    `finished_monotonic`, so a finished-only sweep kept it and `_active_job_id`
    forever — every later start 409'd until the daemon restarted."""
    browser._jobs.clear()
    browser._jobs["hung"] = {
        "state": "launching",
        "message": "x",
        "finished_monotonic": None,
        "last_progress_monotonic": 100.0,
    }
    browser._active_job_id = "hung"

    monkeypatch.setattr(browser.time, "monotonic", lambda: 100.0 + browser._STALLED_SECONDS - 1)
    assert browser.get_google_auth_progress("hung") is not None

    monkeypatch.setattr(browser.time, "monotonic", lambda: 100.0 + browser._STALLED_SECONDS + 1)
    assert browser.get_google_auth_progress("hung") is None
    assert browser._active_job_id is None
    browser._jobs.clear()
