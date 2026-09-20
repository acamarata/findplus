"""Fixtures the two split E6 auth suites share.

Purpose    : test_auth_routes.py (status codes) and test_auth_route_security.py
             (the lock, both origin guards, the password, file modes) need the
             same client and the same job-runner fakes. A conftest rather than
             an importable helper module, so the fixture names do not have to
             be imported into each file and then shadowed by its parameters.
Constraints: every name here is unique to the auth suites (`auth_client`, not
             `client`), so no other cli/tests/api module's own fixtures change
             meaning. Constants live in _auth_helpers.py.

Every fake is installed on `findplus.api.routes_auth` — the names that module
bound into its own namespace — never on the provider modules that define them.
Patching the origin would leave routes_auth's already-imported name alone, and
the "fake" would silently run the real job runner, which launches Chrome.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from findplus.api import create_app, routes_auth
from tests.api._auth_helpers import APPLE_JOB, GOOGLE_JOB


@pytest.fixture
def auth_client(tmp_db):
    return TestClient(create_app())


@pytest.fixture
def apple_installed(monkeypatch):
    monkeypatch.setattr("findplus.providers.apple_findmy.is_available", lambda: (True, ""))


@pytest.fixture
def fake_google(monkeypatch):
    """A synchronous stand-in for browser.py: no thread, no Chrome, no cookie.

    Returns the call list, so a test can assert the runner was NOT reached.
    """
    calls: list[int] = []

    def start(settings):
        calls.append(1)
        return GOOGLE_JOB

    monkeypatch.setattr(routes_auth, "start_google_auth", start)
    monkeypatch.setattr(
        routes_auth,
        "get_google_auth_progress",
        lambda job_id: (
            {"state": "waiting_for_user", "message": "Sign in inside Chrome."}
            if job_id == GOOGLE_JOB
            else None
        ),
    )
    return calls


@pytest.fixture
def fake_apple(monkeypatch):
    monkeypatch.setattr(routes_auth, "start_apple_auth", lambda s, a, p: APPLE_JOB)
    monkeypatch.setattr(
        routes_auth,
        "get_apple_auth_progress",
        lambda job_id: (
            {"state": "needs_2fa", "message": "Enter the code."} if job_id == APPLE_JOB else None
        ),
    )
    monkeypatch.setattr(routes_auth, "submit_apple_code", lambda job_id, code, s: "a@b.com")
