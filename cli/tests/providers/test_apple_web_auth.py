"""The non-interactive Apple sign-in job runner: 2FA, refusals, and the password.

FakeAccount is tests/providers/_fake_findmy.py's FakeAppleAccount: a real
findmy.AsyncAppleAccount subclass with only Apple's servers replaced, so the
job runner is driven through the installed library's own LoginState machine
and 2FA method objects. Nothing opens a socket. `make_account` is monkeypatched
on web_auth itself, the name the module actually calls.
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("findmy")

from findplus.config import get_settings
from findplus.providers.apple_findmy import web_auth
from tests.providers._fake_findmy import GOOD_CODE, SMS_NUMBER
from tests.providers._fake_findmy import FakeAppleAccount as FakeAccount

PASSWORD = "hunter2-not-in-any-job-dict"


@pytest.fixture(autouse=True)
def _clean_jobs():
    """`_jobs` lives for the process, so reset it around every test."""
    web_auth._jobs.clear()
    yield
    web_auth._jobs.clear()


def _settle(job_id: str, *, until: tuple[str, ...] = ("done", "failed", "needs_2fa")) -> dict:
    """Poll the job until it leaves signing_in, with a real wall-clock cap."""
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        progress = web_auth.get_apple_auth_progress(job_id)
        if progress is not None and progress["state"] in until:
            return progress
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} never settled: {web_auth.get_apple_auth_progress(job_id)}")


def _start(tmp_path, monkeypatch, account: FakeAccount) -> tuple[str, object]:
    settings = get_settings(state_dir=tmp_path)
    monkeypatch.setattr(web_auth, "make_account", lambda s: account)
    monkeypatch.setattr(web_auth, "save_account", lambda a, s: None)
    return web_auth.start_apple_auth(settings, "a@b.com", PASSWORD), settings


def test_a_sign_in_without_2fa_reaches_done(tmp_path, monkeypatch) -> None:
    account = FakeAccount(requires_2fa_val=False)
    job_id, _ = _start(tmp_path, monkeypatch, account)

    assert _settle(job_id) == {"state": "done", "message": "Authenticated as a@b.com."}
    assert account.logged_in_as == ("a@b.com", PASSWORD)


def test_a_2fa_sign_in_reaches_needs_2fa_then_done(tmp_path, monkeypatch) -> None:
    account = FakeAccount(requires_2fa_val=True)
    job_id, settings = _start(tmp_path, monkeypatch, account)

    progress = _settle(job_id)
    assert progress == {"state": "needs_2fa", "message": web_auth.MSG_NEEDS_2FA}
    assert account.requests == ["trusted_device"]

    assert web_auth.submit_apple_code(job_id, GOOD_CODE, settings) == "a@b.com"
    assert web_auth.get_apple_auth_progress(job_id) == {
        "state": "done",
        "message": "Authenticated as a@b.com.",
    }


def test_a_refused_code_leaves_the_job_awaiting_another(tmp_path, monkeypatch) -> None:
    account = FakeAccount(requires_2fa_val=True)
    job_id, settings = _start(tmp_path, monkeypatch, account)
    _settle(job_id)

    with pytest.raises(web_auth.InvalidAppleCodeError):
        web_auth.submit_apple_code(job_id, "000000", settings)

    assert web_auth.get_apple_auth_progress(job_id)["state"] == "needs_2fa"


def test_a_refused_code_locks_out_after_five_attempts(tmp_path, monkeypatch) -> None:
    account = FakeAccount(requires_2fa_val=True)
    job_id, settings = _start(tmp_path, monkeypatch, account)
    _settle(job_id)

    for _ in range(5):
        with pytest.raises(web_auth.InvalidAppleCodeError):
            web_auth.submit_apple_code(job_id, "000000", settings)

    assert web_auth.get_apple_auth_progress(job_id)["state"] == "needs_2fa"

    with pytest.raises(web_auth.InvalidAppleCodeError, match="Too many invalid code attempts"):
        web_auth.submit_apple_code(job_id, "000000", settings)

    assert web_auth.get_apple_auth_progress(job_id)["state"] == "failed"


def test_a_post_accept_disk_error_is_not_an_invalid_code(tmp_path, monkeypatch) -> None:
    account = FakeAccount(requires_2fa_val=True)
    job_id, settings = _start(tmp_path, monkeypatch, account)
    _settle(job_id)

    def _boom(*a, **k):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(web_auth, "save_account", _boom)

    # Must raise the underlying error (e.g. OSError) or let a 500 happen,
    # NOT InvalidAppleCodeError which makes the UI blame the user's typing.
    with pytest.raises(OSError, match="read-only"):
        web_auth.submit_apple_code(job_id, GOOD_CODE, settings)


def test_an_unknown_job_id_is_its_own_error(tmp_path) -> None:
    with pytest.raises(web_auth.UnknownAppleJobError):
        web_auth.submit_apple_code("no-such-job", "123456", get_settings(state_dir=tmp_path))
    assert web_auth.get_apple_auth_progress("no-such-job") is None


def test_a_second_start_while_the_first_awaits_a_code_is_refused(tmp_path, monkeypatch) -> None:
    """needs_2fa is not finished: a second sign-in would orphan the first."""
    account = FakeAccount(requires_2fa_val=True)
    job_id, settings = _start(tmp_path, monkeypatch, account)
    assert _settle(job_id)["state"] == "needs_2fa"

    with pytest.raises(web_auth.AppleAuthAlreadyRunningError) as excinfo:
        web_auth.start_apple_auth(settings, "c@d.com", PASSWORD)
    assert excinfo.value.job_id == job_id


def test_the_password_never_lands_in_the_job_dict(tmp_path, monkeypatch) -> None:
    account = FakeAccount(requires_2fa_val=True)
    job_id, _ = _start(tmp_path, monkeypatch, account)
    _settle(job_id)

    job = web_auth._jobs[job_id]
    assert PASSWORD not in job
    assert not any(value == PASSWORD for value in job.values())
    assert PASSWORD not in repr(web_auth.get_apple_auth_progress(job_id))


def test_a_login_failure_marks_the_job_failed(tmp_path, monkeypatch) -> None:
    account = FakeAccount()
    account.login_error = ValueError("Apple rejected the credentials")
    job_id, _ = _start(tmp_path, monkeypatch, account)

    progress = _settle(job_id)
    assert progress["state"] == "failed"
    assert "Apple rejected the credentials" in progress["message"]
    assert PASSWORD not in progress["message"]


def test_an_abandoned_2fa_prompt_does_not_block_apple_signin_forever(monkeypatch) -> None:
    """CR-C-E6 F1: `needs_2fa` is non-terminal, so it had no `finished_monotonic`
    and was never swept, while start_apple_auth() refuses on ANY non-terminal
    job. A user who closed the dialog was locked out until the daemon restarted."""
    web_auth._jobs.clear()
    web_auth._jobs["abandoned"] = {
        "state": "needs_2fa",
        "message": "x",
        "apple_id": "a@b.com",
        "method": None,
        "account": None,
        "finished_monotonic": None,
        "last_progress_monotonic": 100.0,
    }

    monkeypatch.setattr(web_auth.time, "monotonic", lambda: 100.0 + web_auth._STALLED_SECONDS - 1)
    assert web_auth.get_apple_auth_progress("abandoned") is not None

    monkeypatch.setattr(web_auth.time, "monotonic", lambda: 100.0 + web_auth._STALLED_SECONDS + 1)
    assert web_auth.get_apple_auth_progress("abandoned") is None
    assert web_auth._jobs == {}


def test_an_sms_only_account_names_the_text_message(tmp_path, monkeypatch) -> None:
    account = FakeAccount(requires_2fa_val=True)
    account.trusted_device = False
    job_id, settings = _start(tmp_path, monkeypatch, account)

    progress = _settle(job_id)
    assert progress["message"] == web_auth.MSG_NEEDS_SMS.format(number=SMS_NUMBER)
    assert account.requests == ["sms:7"]
    assert web_auth.submit_apple_code(job_id, GOOD_CODE, settings) == "a@b.com"


def test_done_saves_a_signed_in_session_and_releases_the_account(tmp_path, monkeypatch) -> None:
    """With the real save_account: LOGGED_IN on disk, no password, no live account kept."""
    from findplus.providers.apple_findmy import auth

    account = FakeAccount(requires_2fa_val=True)
    settings = get_settings(state_dir=tmp_path)
    monkeypatch.setattr(web_auth, "make_account", lambda s: account)
    job_id = web_auth.start_apple_auth(settings, "a@b.com", PASSWORD)
    _settle(job_id)
    web_auth.submit_apple_code(job_id, GOOD_CODE, settings)

    saved = auth.read_saved_state(settings)
    assert auth.is_signed_in(saved)
    assert saved["account"]["password"] is None
    assert PASSWORD not in (tmp_path / "apple-account.json").read_text(encoding="utf-8")
    assert web_auth._jobs[job_id]["session"] is None
    assert web_auth._jobs[job_id]["method"] is None


def test_an_anisette_failure_fails_the_job_with_an_honest_message(tmp_path, monkeypatch) -> None:
    class NoAnisette(FakeAccount):
        async def get_anisette_headers(self, with_client_info=False, serial="0"):
            raise OSError("network unreachable")

    account = NoAnisette()
    job_id, _ = _start(tmp_path, monkeypatch, account)
    progress = _settle(job_id)
    assert progress["state"] == "failed"
    assert "Local anisette could not start" in progress["message"]
    assert "network unreachable" in progress["message"]
    assert account.logged_in_as is None
