"""Apple sign-in end to end through the HTTP API, then a poll that decrypts a report.

Only findmy's network edge is fake: FakeAppleAccount is a real
findmy.AsyncAppleAccount subclass (tests/providers/_fake_findmy.py). The
routes, the job runner, AppleSession, save/restore, the accessory registry
and report decryption are all the real code. No socket leaves loopback.
"""

from __future__ import annotations

import base64
import datetime
import os
import time

import pytest

findmy = pytest.importorskip("findmy")

from findplus.config import get_settings  # noqa: E402
from findplus.providers.apple_findmy import auth, web_auth  # noqa: E402
from findplus.providers.apple_findmy.accessories import add_accessory  # noqa: E402
from findplus.providers.apple_findmy.provider import AppleFindMyProvider  # noqa: E402
from tests.api._auth_helpers import SAME_ORIGIN_HEADERS  # noqa: E402
from tests.providers._fake_findmy import GOOD_CODE, FakeAppleAccount, encrypted_report  # noqa: E402

SECRET = "correct-horse-battery"
KEY = findmy.KeyPair(bytes(range(1, 29)))


@pytest.fixture(autouse=True)
def _clean_jobs():
    web_auth._jobs.clear()
    yield
    web_auth._jobs.clear()


def _wait_for(auth_client, job_id: str) -> dict:
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        body = auth_client.get(f"/api/auth/apple/progress?job_id={job_id}").json()
        if body["state"] != "signing_in":
            return body
        time.sleep(0.01)
    raise AssertionError("Apple sign-in never left signing_in")


def _sign_in(auth_client, monkeypatch) -> FakeAppleAccount:
    account = FakeAppleAccount(requires_2fa_val=True)
    monkeypatch.setattr(web_auth, "make_account", lambda s: account)
    started = auth_client.post(
        "/api/auth/apple/start",
        json={"apple_id": "a@b.com", "password": SECRET},
        headers=SAME_ORIGIN_HEADERS,
    )
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    assert _wait_for(auth_client, job_id) == {
        "state": "needs_2fa",
        "message": web_auth.MSG_NEEDS_2FA,
    }

    wrong = auth_client.post(
        "/api/auth/apple/code",
        json={"job_id": job_id, "code": "000000"},
        headers=SAME_ORIGIN_HEADERS,
    )
    assert wrong.status_code == 400
    assert _wait_for(auth_client, job_id)["state"] == "needs_2fa"

    done = auth_client.post(
        "/api/auth/apple/code",
        json={"job_id": job_id, "code": GOOD_CODE},
        headers=SAME_ORIGIN_HEADERS,
    )
    assert done.status_code == 200
    assert done.json() == {"state": "done", "message": "Authenticated as a@b.com."}
    assert account.submitted == ["000000", GOOD_CODE]
    return account


def test_apple_2fa_sign_in_then_status_and_a_decrypted_poll(
    auth_client, apple_installed, monkeypatch
) -> None:
    account = _sign_in(auth_client, monkeypatch)
    settings = get_settings()

    saved = settings.state_dir / "apple-account.json"
    if os.name == "posix":
        assert saved.stat().st_mode & 0o777 == 0o600
    assert SECRET not in saved.read_text(encoding="utf-8")
    assert account.logged_in_as == ("a@b.com", SECRET)

    status = auth_client.get("/api/auth/status").json()
    apple = next(p for p in status["providers"] if p["id"] == "apple-find-my")
    assert apple["signed_in"] is True
    assert apple["account"] == "a@b.com"

    # The poller's path: restore from disk through findmy's own from_json.
    when = datetime.datetime.now(datetime.UTC).replace(microsecond=0)
    real_restore = auth.restore_account

    def restore(s):
        restored = FakeAppleAccount.from_json(auth.read_saved_state(s))
        assert real_restore(s).login_state == restored.login_state
        restored.reports = [encrypted_report(KEY, 48.8584, 2.2945, when)]
        return restored

    monkeypatch.setattr(auth, "restore_account", restore)
    record = add_accessory(
        "Keys", settings, private_key_b64=base64.b64encode(KEY.private_key_bytes).decode()
    )
    [obs] = AppleFindMyProvider().locate(record["device_id"], "Keys")
    assert (obs.latitude_e7, obs.longitude_e7) == (488584000, 22945000)
    assert obs.observed_at == when
    assert obs.accuracy_meters is None
