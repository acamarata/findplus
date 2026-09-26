"""PUT /api/alerts/channels/webhook: masked-value refusal and "blank means
keep" semantics (UAT6 N02, blocking).

Purpose : The Alerts tab used to prefill #fp-webhook-url with the server's
          own MASKED url (channels_response()'s mask_url()); an unchanged
          Save then wrote that literal masked string back as the real URL,
          silently breaking the webhook. The client-side fix (alerts_
          webhook.js) never puts the mask in the field at all; these tests
          cover the server's own half of the fix -- the same guarantee for
          any other caller of the route, defence in depth.
Constraints: Each case proves the credential on disk before/after directly
          (via GET .../channels, the only read surface -- never psql/hand
          inspection per this app's own rules), not just the response code.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from findplus.db.session import session_scope
from findplus.ingest import upsert_device


@pytest.fixture
def client(tmp_db):
    from findplus.api import create_app

    with session_scope() as session:
        upsert_device(session, "dev1", "Tag1")
    return TestClient(create_app())


def test_put_webhook_rejects_the_ellipsis_masked_shape(client: TestClient) -> None:
    """mask_url()'s common shape ("scheme://host/…1234") must never be
    accepted as a real URL, even though it is a syntactically plausible
    string (this is the shape a real, long-tailed webhook path masks to)."""
    res = client.put(
        "/api/alerts/channels/webhook",
        json={"url": "http://localhost:9999/…1234", "secret": None},
    )
    assert res.status_code == 422
    assert "masked" in res.json()["detail"]


def test_put_webhook_rejects_the_bare_star_masked_shape(client: TestClient) -> None:
    """mask_url()'s short-tail/unparseable shape (a bare or near-bare "***")
    -- the exact string UAT6 N02 found prefilled in the field."""
    res = client.put(
        "/api/alerts/channels/webhook",
        json={"url": "http://127.0.0.1:9/***", "secret": None},
    )
    assert res.status_code == 422
    assert "masked" in res.json()["detail"]


def test_put_webhook_with_no_existing_webhook_and_no_url_is_422(client: TestClient) -> None:
    """An omitted url means "keep the current one" -- with nothing saved
    yet, there is nothing to keep, so it is required the same as before."""
    res = client.put("/api/alerts/channels/webhook", json={"secret": "s3cret"})
    assert res.status_code == 422


def test_put_webhook_omitted_url_keeps_the_saved_one(client: TestClient) -> None:
    """Save once with a real URL, then PUT again with url omitted (only the
    secret changing) -- the URL on disk must be untouched."""
    first = client.put(
        "/api/alerts/channels/webhook",
        json={"url": "https://example.com/hook-abcd", "secret": None},
    )
    assert first.status_code == 200, first.text

    second = client.put("/api/alerts/channels/webhook", json={"secret": "new-secret"})
    assert second.status_code == 200, second.text
    body = client.get("/api/alerts/channels").json()["webhook"]
    assert body["configured"] is True
    assert body["url"] == "https://example.com/…abcd"
    assert body["has_secret"] is True


def test_put_webhook_omitted_secret_keeps_the_saved_one(client: TestClient) -> None:
    """UAT6 N02 ("webhook secret"): the secret field is never prefilled, so
    it used to be blank on every save -- resaving just the URL silently
    cleared a working secret. Omitting `secret` from the request now leaves
    it exactly as it was."""
    first = client.put(
        "/api/alerts/channels/webhook",
        json={"url": "https://example.com/hook-1111", "secret": "first-secret"},
    )
    assert first.status_code == 200, first.text

    second = client.put(
        "/api/alerts/channels/webhook", json={"url": "https://example.com/hook-2222"}
    )
    assert second.status_code == 200, second.text
    body = client.get("/api/alerts/channels").json()["webhook"]
    assert body["has_secret"] is True, "an omitted secret must not clear the saved one"
    assert body["url"] == "https://example.com/…2222"


def test_put_webhook_empty_string_secret_clears_it(client: TestClient) -> None:
    """`null` and an omitted key both mean "keep" (pydantic reads them
    identically); an empty STRING is the one value still distinguishable
    from "unset", so it is what an explicit clear looks like on this route.
    The dashboard's own saveWebhook() never sends it (an empty field is
    submitted as omitted, per this module's own docstring) -- this is for a
    direct API caller."""
    first = client.put(
        "/api/alerts/channels/webhook",
        json={"url": "https://example.com/hook-3333", "secret": "will-be-cleared"},
    )
    assert first.status_code == 200, first.text

    second = client.put(
        "/api/alerts/channels/webhook",
        json={"url": "https://example.com/hook-3333", "secret": ""},
    )
    assert second.status_code == 200, second.text
    body = client.get("/api/alerts/channels").json()["webhook"]
    assert body["has_secret"] is False
