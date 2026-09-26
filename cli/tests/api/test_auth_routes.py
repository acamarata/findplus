"""Status codes for every E6 auth route, against a fake job runner.

specs/auth-ui.md §9. The lock, the two origin guards and the secret-handling
invariants are the sibling file's, test_auth_route_security.py; fixtures for
both live in _auth_helpers.py. Nothing here imports selenium or findmy, opens
a socket, or waits on a real background thread.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from findplus.api import routes_auth
from tests.api._auth_helpers import (
    APPLE_CODE_BODY,
    APPLE_JOB,
    APPLE_START_BODY,
    GOOGLE_JOB,
    SAME_ORIGIN_HEADERS,
)


# ------------------------------------------------------------------- status
def test_status_returns_a_list_with_google_and_needs_field(auth_client: TestClient) -> None:
    res = auth_client.get("/api/auth/status")
    assert res.status_code == 200
    providers = res.json()["providers"]
    assert providers
    for row in providers:
        assert set(row) == {"id", "signed_in", "account", "method", "last_checked", "needs"}
        assert isinstance(row["needs"], list)
    assert "google-find-hub" in {row["id"] for row in providers}


# ------------------------------------------------------------------- google
def test_google_start_returns_202_and_a_job_id(auth_client: TestClient, fake_google) -> None:
    res = auth_client.post("/api/auth/google/start", headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 202
    assert res.json() == {"job_id": GOOGLE_JOB}
    assert len(fake_google) == 1


def test_google_start_second_call_is_409_with_flat_body(
    auth_client: TestClient, monkeypatch
) -> None:
    seen: list[int] = []

    def start(settings):
        if seen:
            raise routes_auth.GoogleAuthAlreadyRunningError("job-1")
        seen.append(1)
        return "job-1"

    monkeypatch.setattr(routes_auth, "start_google_auth", start)

    assert (
        auth_client.post("/api/auth/google/start", headers=SAME_ORIGIN_HEADERS).status_code == 202
    )
    res = auth_client.post("/api/auth/google/start", headers=SAME_ORIGIN_HEADERS)

    assert res.status_code == 409
    # Exact equality, not a substring: a regression to a nested
    # {"detail": {"detail": ...}} body must fail loudly.
    assert res.json() == {"detail": "A Google sign-in is already in progress.", "job_id": "job-1"}


def test_google_start_chrome_missing_is_400(auth_client: TestClient, monkeypatch) -> None:
    def start(settings):
        raise routes_auth.ChromeNotFoundError(
            "Google Chrome was not found on this machine. Install it."
        )

    monkeypatch.setattr(routes_auth, "start_google_auth", start)

    res = auth_client.post("/api/auth/google/start", headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 400
    assert "Chrome" in res.json()["detail"]


def test_google_progress_without_job_id_is_422(auth_client: TestClient, fake_google) -> None:
    assert auth_client.get("/api/auth/google/progress").status_code == 422


def test_google_progress_unknown_job_id_is_404(auth_client: TestClient, fake_google) -> None:
    res = auth_client.get("/api/auth/google/progress?job_id=nope")
    assert res.status_code == 404
    assert res.json() == {"detail": "unknown or expired job_id"}


def test_google_progress_known_job_id_returns_chrome_found_key(
    auth_client: TestClient,
    fake_google,
) -> None:
    res = auth_client.get(f"/api/auth/google/progress?job_id={GOOGLE_JOB}")
    assert res.status_code == 200
    body = res.json()
    assert body["state"] == "waiting_for_user"
    assert isinstance(body["chrome_found"], bool)


# --------------------------------------------------------- google/cancel (N23)
def test_google_cancel_returns_the_cancelled_state(auth_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(routes_auth, "cancel_google_auth", lambda job_id: job_id == GOOGLE_JOB)

    res = auth_client.post(
        "/api/auth/google/cancel", json={"job_id": GOOGLE_JOB}, headers=SAME_ORIGIN_HEADERS
    )

    assert res.status_code == 200
    assert res.json() == {"state": "failed", "message": routes_auth.MSG_CANCELLED}


def test_google_cancel_unknown_job_is_404(auth_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(routes_auth, "cancel_google_auth", lambda job_id: False)

    res = auth_client.post(
        "/api/auth/google/cancel", json={"job_id": "nope"}, headers=SAME_ORIGIN_HEADERS
    )

    assert res.status_code == 404


# -------------------------------------------------------------------- apple
def test_apple_start_needs_2fa_then_code_reaches_done(
    auth_client: TestClient,
    apple_installed,
    fake_apple,
) -> None:
    started = auth_client.post(
        "/api/auth/apple/start", json=APPLE_START_BODY, headers=SAME_ORIGIN_HEADERS
    )
    assert started.status_code == 202
    assert started.json() == {"job_id": APPLE_JOB}

    progress = auth_client.get(f"/api/auth/apple/progress?job_id={APPLE_JOB}")
    assert progress.status_code == 200
    assert progress.json()["state"] == "needs_2fa"

    done = auth_client.post(
        "/api/auth/apple/code", json=APPLE_CODE_BODY, headers=SAME_ORIGIN_HEADERS
    )
    assert done.status_code == 200
    assert done.json()["state"] == "done"


def test_apple_code_wrong_is_400(
    auth_client: TestClient,
    apple_installed,
    fake_apple,
    monkeypatch,
) -> None:
    def refuse(job_id, code, settings):
        raise routes_auth.InvalidAppleCodeError("bad")

    monkeypatch.setattr(routes_auth, "submit_apple_code", refuse)

    res = auth_client.post(
        "/api/auth/apple/code", json=APPLE_CODE_BODY, headers=SAME_ORIGIN_HEADERS
    )
    assert res.status_code == 400
    assert res.json() == {"detail": "invalid or expired code"}


def test_apple_code_unknown_job_is_404(
    auth_client: TestClient,
    apple_installed,
    fake_apple,
    monkeypatch,
) -> None:
    def unknown(job_id, code, settings):
        raise routes_auth.UnknownAppleJobError("nope")

    monkeypatch.setattr(routes_auth, "submit_apple_code", unknown)

    res = auth_client.post(
        "/api/auth/apple/code", json=APPLE_CODE_BODY, headers=SAME_ORIGIN_HEADERS
    )
    assert res.status_code == 404


def test_apple_accessories_missing_both_fields_is_422(
    auth_client: TestClient, apple_installed
) -> None:
    # No headers: this route is deliberately outside _require_origin_signal.
    res = auth_client.post("/api/apple/accessories", json={"name": "x"})
    assert res.status_code == 422


def test_apple_accessories_apple_not_installed_is_503(auth_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "findplus.providers.apple_findmy.is_available",
        lambda: (False, "pip install 'findplus[apple]'"),
    )
    res = auth_client.post("/api/apple/accessories", json={"name": "x", "private_key_b64": "y"})
    assert res.status_code == 503
    assert "findplus[apple]" in res.json()["detail"]
