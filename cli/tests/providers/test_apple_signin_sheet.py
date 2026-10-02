"""The Apple sign-in sheet: phases, trusted device vs text message, cancel.

Driven through FindMy.py's real LoginState machine and 2FA method objects with
only Apple's servers faked (tests/providers/_fake_findmy.py). No socket opens.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

pytest.importorskip("findmy")

from findplus.providers.apple_findmy import signin_sheet, web_auth
from tests.providers._fake_findmy import GOOD_CODE, SMS_NUMBER
from tests.providers._fake_findmy import FakeAppleAccount as FakeAccount

PASSWORD = "hunter2-sheet-secret"


@pytest.fixture(autouse=True)
def _clean_jobs():
    web_auth._jobs.clear()
    yield
    web_auth._jobs.clear()


def _settings(tmp_path, url="http://127.0.0.1:9/a"):
    """Only the two fields the sheet reads; the Apple calls themselves are faked."""
    return SimpleNamespace(state_dir=tmp_path, apple_anisette_url=url)


def _start(tmp_path, monkeypatch, account, saved=None):
    settings = _settings(tmp_path)
    monkeypatch.setattr(web_auth, "make_account", lambda s: account)
    monkeypatch.setattr(web_auth, "save_account", lambda a, s: (saved or []).append(a))
    return web_auth.start_apple_auth(settings, "a@b.com", PASSWORD), settings


def _settle(settings, job_id, phases=("needs_code", "success", "error", "cancelled")):
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        status = signin_sheet.sheet_status(settings, job_id)
        if status["phase"] in phases:
            return status
        time.sleep(0.01)
    raise AssertionError(signin_sheet.sheet_status(settings, job_id))


def test_no_job_is_idle(tmp_path) -> None:
    assert signin_sheet.sheet_status(_settings(tmp_path))["phase"] == "idle"


def test_trusted_device_first_with_a_text_option(tmp_path, monkeypatch) -> None:
    job_id, settings = _start(tmp_path, monkeypatch, FakeAccount(requires_2fa_val=True))
    status = _settle(settings, job_id)
    assert status["phase"] == "needs_code"
    assert status["message"] == "Enter the 6-digit code shown on your iPhone, iPad or Mac."
    assert status["second_factor"] == {
        "kind": "trusted_device",
        "phone": None,
        "can_text": True,
        "sms_options": [{"id": 7, "phone": SMS_NUMBER}],
    }
    assert PASSWORD not in str(status)


def test_text_me_instead_switches_to_sms_then_the_code_works(tmp_path, monkeypatch) -> None:
    account = FakeAccount(requires_2fa_val=True)
    job_id, settings = _start(tmp_path, monkeypatch, account)
    _settle(settings, job_id)
    answer = signin_sheet.text_me(job_id, 7)
    assert answer["phone"] == SMS_NUMBER and SMS_NUMBER in answer["message"]
    assert account.requests == ["trusted_device", "sms:7"]
    status = signin_sheet.sheet_status(settings, job_id)
    assert status["second_factor"]["kind"] == "sms"
    assert web_auth.submit_apple_code(job_id, GOOD_CODE, settings) == "a@b.com"
    done = signin_sheet.sheet_status(settings)
    assert done["phase"] == "success" and done["message"] == "Connected as a@b.com."


def test_text_me_to_an_unknown_number_is_refused(tmp_path, monkeypatch) -> None:
    job_id, settings = _start(tmp_path, monkeypatch, FakeAccount(requires_2fa_val=True))
    _settle(settings, job_id)
    with pytest.raises(signin_sheet.SheetError) as info:
        signin_sheet.text_me(job_id, 99)
    assert info.value.status == 422


def test_cancel_while_waiting_for_a_code(tmp_path, monkeypatch) -> None:
    job_id, settings = _start(tmp_path, monkeypatch, FakeAccount(requires_2fa_val=True))
    _settle(settings, job_id)
    assert signin_sheet.cancel(job_id) is True
    assert signin_sheet.sheet_status(settings, job_id)["phase"] == "cancelled"
    with pytest.raises(web_auth.InvalidAppleCodeError):
        web_auth.submit_apple_code(job_id, GOOD_CODE, settings)
    assert signin_sheet.cancel(job_id) is False  # already over
    # The old progress route still reads a plain failed/cancelled job.
    assert web_auth.get_apple_auth_progress(job_id)["state"] == "failed"


def test_cancel_during_login_saves_nothing(tmp_path, monkeypatch) -> None:
    account = FakeAccount(requires_2fa_val=False)
    saved: list = []
    gate = {"go": False}
    original = account.login

    async def slow_login(username, password):
        while not gate["go"]:
            time.sleep(0.005)
        return await original(username, password)

    account.login = slow_login
    job_id, settings = _start(tmp_path, monkeypatch, account, saved)
    assert signin_sheet.cancel(job_id) is True
    gate["go"] = True
    time.sleep(0.2)
    assert saved == []
    assert signin_sheet.sheet_status(settings, job_id)["phase"] == "cancelled"


def _cancel_inside_the_code_check(job_id) -> None:
    """Make Apple's code check let the sheet's Cancel land before it answers."""
    job = web_auth._jobs[job_id]
    real = job["method"]

    class Racing:
        def __getattr__(self, name):
            return getattr(real, name)

        async def submit(self, code):
            state = await real.submit(code)
            with web_auth._lock:  # what signin_sheet.cancel records, minus the session close
                job["cancelled"] = True
                job["state"], job["message"] = "failed", signin_sheet.MSG_CANCELLED
            return state

    job["method"] = Racing()


def test_cancel_during_the_code_check_saves_nothing(tmp_path, monkeypatch) -> None:
    """r12 #11: Cancel while Apple checks the code must never save the account."""
    saved: list = []
    job_id, settings = _start(tmp_path, monkeypatch, FakeAccount(requires_2fa_val=True), saved)
    _settle(settings, job_id)
    _cancel_inside_the_code_check(job_id)
    with pytest.raises(web_auth.InvalidAppleCodeError):
        web_auth.submit_apple_code(job_id, GOOD_CODE, settings)
    assert saved == []
    assert signin_sheet.sheet_status(settings, job_id)["phase"] == "cancelled"


def test_cancel_after_apple_accepted_is_too_late(tmp_path, monkeypatch) -> None:
    saved: list = []
    job_id, settings = _start(tmp_path, monkeypatch, FakeAccount(requires_2fa_val=True), saved)
    _settle(settings, job_id)
    web_auth._jobs[job_id]["saving"] = True
    assert signin_sheet.cancel(job_id) is False


def test_first_run_without_anisette_libs_says_preparing(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, url=None)
    with web_auth._lock:
        web_auth._jobs["j"] = {
            "state": "signing_in",
            "message": web_auth.MSG_SIGNING_IN,
            "apple_id": "a@b.com",
            "finished_monotonic": None,
            "last_progress_monotonic": time.monotonic(),
        }
    status = signin_sheet.sheet_status(settings, "j")
    assert status["phase"] == "preparing" and "one-time download" in status["message"]
    (tmp_path / "anisette-libs.bin").write_bytes(b"x")
    assert signin_sheet.sheet_status(settings, "j")["phase"] == "signing_in"


def test_unknown_job_is_a_404(tmp_path) -> None:
    with pytest.raises(signin_sheet.SheetError) as info:
        signin_sheet.sheet_status(_settings(tmp_path), "nope")
    assert info.value.status == 404
