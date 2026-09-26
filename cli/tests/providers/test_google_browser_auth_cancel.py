"""`cancel_google_auth()` (UAT6 N23: Cancel while waiting on Chrome).

Split out of test_google_browser_auth.py to keep that file under the
per-file line cap (PRI rule 7) once cancel support landed. Reuses that
file's FakeDriver and `_chrome()` helper rather than duplicating them, and
its `_clean_jobs` autouse fixture -- imported by name, not redefined, so the
two files cannot drift on how `_jobs`/`_active_job_id` get reset per test.
"""

from __future__ import annotations

from findplus.config import get_settings
from findplus.providers.google_findhub import browser

from .test_google_browser_auth import FakeDriver, _chrome, _clean_jobs  # noqa: F401


def test_cancel_quits_the_driver_and_marks_the_job_failed(tmp_path, monkeypatch) -> None:
    from findplus.cli import doctor

    monkeypatch.setattr(doctor, "check_chrome", _chrome(True))
    monkeypatch.setattr(browser, "_run_google_auth", lambda job_id, settings: None)
    job_id = browser.start_google_auth(get_settings(state_dir=tmp_path))
    driver = FakeDriver()
    browser._jobs[job_id]["driver"] = driver

    assert browser.cancel_google_auth(job_id) is True

    assert driver.quit_calls == 1
    assert browser.get_google_auth_progress(job_id) == {
        "state": "failed",
        "message": browser.MSG_CANCELLED,
    }
    assert browser._active_job_id is None


def test_cancel_with_no_driver_yet_still_ends_the_job(tmp_path, monkeypatch) -> None:
    """The Cancel click can land before Chrome ever opens (the /start request
    itself is still in flight): no driver to quit, but the job still ends."""
    from findplus.cli import doctor

    monkeypatch.setattr(doctor, "check_chrome", _chrome(True))
    monkeypatch.setattr(browser, "_run_google_auth", lambda job_id, settings: None)
    job_id = browser.start_google_auth(get_settings(state_dir=tmp_path))

    assert browser.cancel_google_auth(job_id) is True
    assert browser.get_google_auth_progress(job_id)["state"] == "failed"


def test_cancel_of_an_unknown_or_finished_job_is_false(tmp_path, monkeypatch) -> None:
    from findplus.cli import doctor

    assert browser.cancel_google_auth("no-such-job") is False

    monkeypatch.setattr(doctor, "check_chrome", _chrome(True))
    monkeypatch.setattr(browser, "_run_google_auth", lambda job_id, settings: None)
    job_id = browser.start_google_auth(get_settings(state_dir=tmp_path))
    browser._set_progress(job_id, "done", "Authenticated as a@b.com.")

    assert browser.cancel_google_auth(job_id) is False


def test_a_cancelled_job_ignores_a_late_outcome_from_the_auth_thread(tmp_path, monkeypatch) -> None:
    """The background thread can still be mid-flight when cancel runs (it
    raises from the quit()'d driver a moment later); its own _set_progress
    call must not overwrite "Sign-in cancelled." (UAT6 N23)."""
    from findplus.cli import doctor

    monkeypatch.setattr(doctor, "check_chrome", _chrome(True))
    monkeypatch.setattr(browser, "_run_google_auth", lambda job_id, settings: None)
    job_id = browser.start_google_auth(get_settings(state_dir=tmp_path))

    browser.cancel_google_auth(job_id)
    browser._set_progress(job_id, "failed", "some selenium error after quit()")

    assert browser.get_google_auth_progress(job_id) == {
        "state": "failed",
        "message": browser.MSG_CANCELLED,
    }
