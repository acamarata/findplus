"""The app lock, both origin guards, the Apple password and the profile mode.

specs/auth-ui.md §8-§9. Two distinct 403 mechanisms are under test and must not
be collapsed into one case:

* `OriginGuardMiddleware` (api/middleware.py) refuses a header that is PRESENT
  and disallowed, on every `/api/` path. Pre-existing.
* `_require_origin_signal` (api/routes_auth.py) refuses a request carrying
  NEITHER `Origin` nor `Sec-Fetch-Site`, and only on the three routes that
  start a sign-in. New in P2-E6-W3-S1-T2/T3, and deliberately not applied to
  `POST /api/apple/accessories` or to any older route, which the CLI and the
  MCP client reach with no headers at all.

Route status codes are the sibling file's, test_auth_routes.py.
"""

from __future__ import annotations

import logging
import os
import re
import time

import pytest
from fastapi.testclient import TestClient

from findplus.api import create_app
from tests.api._auth_helpers import (
    APPLE_CODE_BODY,
    APPLE_START_BODY,
    EVIL,
    SAME_ORIGIN_HEADERS,
)


# ------------------------------------------------------------ origin guards
@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/auth/google/start", None),
        ("/api/auth/apple/start", APPLE_START_BODY),
        ("/api/auth/apple/code", APPLE_CODE_BODY),
    ],
)
def test_missing_origin_and_sec_fetch_site_is_403_on_the_three_mutating_auth_routes(
    auth_client: TestClient,
    apple_installed,
    fake_google,
    fake_apple,
    path: str,
    body,
) -> None:
    """`_require_origin_signal`: neither header present. A different code path
    from test_a_foreign_origin_cannot_start_a_google_signin below."""
    res = auth_client.post(path, json=body) if body else auth_client.post(path)
    assert res.status_code == 403
    assert res.json() == {"detail": "missing Origin/Sec-Fetch-Site"}


def test_a_foreign_origin_cannot_start_a_google_signin(
    auth_client: TestClient, fake_google
) -> None:
    """OriginGuardMiddleware: the Origin is PRESENT and disallowed, so the
    request is refused before it ever reaches `_require_origin_signal`."""
    res = auth_client.post("/api/auth/google/start", headers={"Origin": EVIL})
    assert res.status_code == 403
    assert res.json()["detail"] != "missing Origin/Sec-Fetch-Site"
    assert len(fake_google) == 0


def test_the_accessories_route_is_not_subject_to_the_new_signal_guard(
    auth_client: TestClient,
    apple_installed,
) -> None:
    """The control for the parametrised case above: a headerless POST here is
    refused on its body, not on its headers (specs/auth-ui.md §8's route list)."""
    res = auth_client.post("/api/apple/accessories", json={"name": "x"})
    assert res.status_code != 403


# ----------------------------------------------------------------- the lock
def _auth_routes() -> list[tuple[str, str]]:
    """The E6 paths, discovered from the live route table, not hand-listed.

    cli/tests/test_lock_sweep.py already sweeps every non-public route
    dynamically and covers all seven of these. Rather than re-implement a
    parallel hand-rolled list that can drift from it, this asserts the same
    discovery finds them and that the lock beats the newer origin guard.
    """
    from tests.test_api_routes_snapshot import _app_routes

    return sorted(
        (method, route.path)
        for route in _app_routes(create_app())
        for method in route.methods
        if route.path.startswith("/api/auth/") or route.path == "/api/apple/accessories"
    )


_E6_ROUTES = _auth_routes()


def test_the_dynamic_sweep_sees_all_seven_new_routes() -> None:
    assert len(_E6_ROUTES) == 7, _E6_ROUTES


@pytest.mark.parametrize("method,path", _E6_ROUTES)
def test_every_e6_route_401s_while_locked(locked_client, method: str, path: str) -> None:
    """SessionAuthMiddleware runs before any handler body, so the lock wins over
    `_require_origin_signal` — sent WITH the headers, this is still a 401."""
    concrete = re.sub(r"\{[^}]+\}", "0", path)
    call = getattr(locked_client, method.lower())
    kwargs = {"headers": SAME_ORIGIN_HEADERS}
    if method != "GET":
        kwargs["json"] = {}
    res = call(concrete, **kwargs)
    assert res.status_code == 401, f"{method} {path} -> {res.status_code}"
    assert res.json() == {"detail": "Locked. Enter your PIN to continue.", "locked": True}


# --------------------------------------------------------------- the secret
def test_apple_password_never_reaches_a_log_line_or_a_response(
    auth_client: TestClient,
    apple_installed,
    monkeypatch,
    caplog,
) -> None:
    """The real job runner, with only findmy faked: the password must stay in
    the thread's frame and reach neither a log record nor any response body."""
    from findplus.providers.apple_findmy import web_auth
    from tests.providers.test_apple_web_auth import FakeAccount

    secret = "hunter2-secret"
    web_auth._jobs.clear()
    monkeypatch.setattr(web_auth, "make_account", lambda s: FakeAccount(requires_2fa_val=True))
    monkeypatch.setattr(web_auth, "save_account", lambda a, s: None)
    caplog.set_level(logging.DEBUG)

    bodies = []
    started = auth_client.post(
        "/api/auth/apple/start",
        json={"apple_id": "a@b.com", "password": secret},
        headers=SAME_ORIGIN_HEADERS,
    )
    assert started.status_code == 202
    bodies.append(started.text)
    job_id = started.json()["job_id"]

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        res = auth_client.get(f"/api/auth/apple/progress?job_id={job_id}")
        bodies.append(res.text)
        if res.json()["state"] in ("needs_2fa", "done", "failed"):
            break
        time.sleep(0.01)

    assert res.json()["state"] == "needs_2fa"
    assert secret not in caplog.text
    assert not any(secret in body for body in bodies)
    assert not any(value == secret for value in web_auth._jobs[job_id].values())
    web_auth._jobs.clear()


@pytest.mark.posix_only
def test_the_chrome_profile_dir_ends_up_0700(tmp_path, monkeypatch) -> None:
    """browser.py creates the profile 0700; doctor_perms.py then checks it."""
    from findplus.cli import doctor
    from findplus.config import get_settings
    from findplus.providers.google_findhub import browser

    settings = get_settings(state_dir=tmp_path)
    monkeypatch.setattr(
        doctor,
        "check_chrome",
        lambda: doctor.DoctorCheck("chrome", "Google Chrome", True, "fake"),
    )

    def stub_patch(patched_settings, job_id):
        # What the real _patch_vendor_chrome's inner factory does, minus Chrome.
        patched_settings.chrome_profile_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(patched_settings.chrome_profile_dir, 0o700)

    monkeypatch.setattr(browser, "_patch_vendor_chrome", stub_patch)
    monkeypatch.setattr(
        "findplus.providers.google_findhub.client.FindHubClient",
        lambda s: type("C", (), {"authenticate": lambda self: "a@b.com"})(),
    )
    browser._jobs.clear()
    browser._active_job_id = None

    browser.start_google_auth(settings)
    # stub_patch runs on a background thread and does mkdir() then chmod() as
    # two separate calls (real code, PRI hard rule 9: mode= on mkdir() is
    # masked by umask). Polling only `.exists()` races that gap: mkdir()
    # makes the directory exist a moment before chmod() lands, and under a
    # full-suite run with other daemon threads contending for the GIL that
    # gap can outlast this loop's 10 ms tick, so the assertion below could
    # observe the pre-chmod mode. Wait for the actual end state (the mode
    # bits themselves) instead of a proxy for it.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not (
        settings.chrome_profile_dir.is_dir()
        and os.stat(settings.chrome_profile_dir).st_mode & 0o777 == 0o700
    ):
        time.sleep(0.01)

    assert settings.chrome_profile_dir.is_dir()
    assert os.stat(settings.chrome_profile_dir).st_mode & 0o777 == 0o700
    assert doctor.check_sensitive_file_perms(tmp_path).passed
    browser._jobs.clear()
    browser._active_job_id = None
