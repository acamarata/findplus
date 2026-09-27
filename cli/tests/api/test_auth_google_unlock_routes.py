"""POST/GET /api/auth/google/unlock/*: the unlock step over HTTP.

Purpose    : Status codes, the Origin guard, the 409 flat body and the job-id
             plumbing, against a fake job runner. No browser, no vendor.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from findplus.api import _routes_auth_google_unlock as routes
from tests.api._auth_helpers import EVIL, SAME_ORIGIN_HEADERS

START = "/api/auth/google/unlock/start"
PROGRESS = "/api/auth/google/unlock/progress"
CANCEL = "/api/auth/google/unlock/cancel"
JOB = "unlock-job-1"


@pytest.fixture
def fake_unlock(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(routes, "start_google_unlock", lambda s: calls.append(1) or JOB)
    monkeypatch.setattr(
        routes,
        "get_google_unlock_progress",
        lambda job_id: (
            {"state": "waiting_for_user", "message": "Enter your screen lock."}
            if job_id == JOB
            else None
        ),
    )
    monkeypatch.setattr(routes, "cancel_google_unlock", lambda job_id: job_id == JOB)
    return calls


def test_start_returns_202_and_a_job_id(auth_client: TestClient, fake_unlock) -> None:
    res = auth_client.post(START, headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 202
    assert res.json() == {"job_id": JOB}
    assert len(fake_unlock) == 1


def test_start_is_409_flat_when_one_is_running(auth_client: TestClient, monkeypatch) -> None:
    def start(settings):
        raise routes.GoogleUnlockAlreadyRunningError(JOB)

    monkeypatch.setattr(routes, "start_google_unlock", start)
    res = auth_client.post(START, headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 409
    assert res.json() == {"detail": "A Google unlock is already in progress.", "job_id": JOB}


@pytest.mark.parametrize("headers", [{}, {"Origin": EVIL}], ids=["headerless", "foreign"])
def test_start_and_cancel_need_same_origin_proof(
    auth_client: TestClient, fake_unlock, headers
) -> None:
    assert auth_client.post(START, headers=headers).status_code == 403
    assert auth_client.post(CANCEL, json={"job_id": JOB}, headers=headers).status_code == 403
    assert fake_unlock == []


def test_progress_returns_the_state(auth_client: TestClient, fake_unlock) -> None:
    res = auth_client.get(f"{PROGRESS}?job_id={JOB}")
    assert res.status_code == 200
    assert res.json()["state"] == "waiting_for_user"


def test_progress_without_job_id_is_422(auth_client: TestClient, fake_unlock) -> None:
    assert auth_client.get(PROGRESS).status_code == 422


def test_progress_unknown_job_is_404(auth_client: TestClient, fake_unlock) -> None:
    assert auth_client.get(f"{PROGRESS}?job_id=nope").status_code == 404


def test_cancel_returns_the_cancelled_state(auth_client: TestClient, fake_unlock) -> None:
    res = auth_client.post(CANCEL, json={"job_id": JOB}, headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 200
    assert res.json()["state"] == "failed"


def test_cancel_unknown_job_is_404(auth_client: TestClient, fake_unlock) -> None:
    res = auth_client.post(CANCEL, json={"job_id": "nope"}, headers=SAME_ORIGIN_HEADERS)
    assert res.status_code == 404
