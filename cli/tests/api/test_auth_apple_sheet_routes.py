"""The Apple sheet's HTTP: status, cancel and "Text me instead", next to the old routes.

The provider module is faked at the names the route module calls; no findmy,
no Apple. The lock and the Origin guards are covered by the sweeps.
"""

from __future__ import annotations

import pytest

from findplus.api import _routes_auth_apple_sheet as sheet_routes
from findplus.providers.apple_findmy import signin_sheet
from tests.api._auth_helpers import SAME_ORIGIN_HEADERS


def test_status_with_no_job_is_idle(auth_client, apple_installed) -> None:
    res = auth_client.get("/api/auth/apple/status")
    assert res.status_code == 200
    body = res.json()
    assert body["phase"] == "idle" and body["available"] is True and body["install_hint"] is None


def test_status_names_the_install_hint_without_the_extra(auth_client, monkeypatch) -> None:
    monkeypatch.setattr(
        "findplus.providers.apple_findmy.is_available", lambda: (False, "pip install x")
    )
    body = auth_client.get("/api/auth/apple/status").json()
    assert body["available"] is False and body["install_hint"] == "pip install x"


def test_unknown_job_status_is_404(auth_client, apple_installed) -> None:
    assert auth_client.get("/api/auth/apple/status?job_id=nope").status_code == 404


def test_cancel_unknown_job_is_404(auth_client) -> None:
    res = auth_client.post(
        "/api/auth/apple/cancel", json={"job_id": "x"}, headers=SAME_ORIGIN_HEADERS
    )
    assert res.status_code == 404


def test_cancel_a_live_job(auth_client, monkeypatch) -> None:
    monkeypatch.setattr(signin_sheet, "cancel", lambda job_id: job_id == "j")
    res = auth_client.post(
        "/api/auth/apple/cancel", json={"job_id": "j"}, headers=SAME_ORIGIN_HEADERS
    )
    assert res.json() == {"phase": "cancelled", "message": "Cancelled. Nothing changed."}


@pytest.mark.parametrize("status", [404, 409, 422, 502])
def test_text_maps_refusals(auth_client, apple_installed, monkeypatch, status) -> None:
    def refuse(job_id, phone_id):
        raise signin_sheet.SheetError(status, "plain words")

    monkeypatch.setattr(sheet_routes.signin_sheet, "text_me", refuse)
    res = auth_client.post(
        "/api/auth/apple/text", json={"job_id": "j", "phone_id": 7}, headers=SAME_ORIGIN_HEADERS
    )
    assert res.status_code == status and res.json()["detail"] == "plain words"


@pytest.mark.parametrize("path", ["/api/auth/apple/cancel", "/api/auth/apple/text"])
def test_sheet_posts_need_an_origin_signal(auth_client, apple_installed, path) -> None:
    assert auth_client.post(path, json={"job_id": "j"}).status_code == 403
