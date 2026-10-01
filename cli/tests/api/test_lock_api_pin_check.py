"""POST /api/settings/pin/check: is this the PIN? Changes nothing, never reads from a URL."""

from __future__ import annotations

from fastapi.testclient import TestClient

from findplus.appsettings import load_settings
from findplus.db.session import session_scope
from tests.api._lock_helpers import PIN, _set_pin, client, store  # noqa: F401


def test_the_right_pin_is_ok_and_nothing_changes(client: TestClient) -> None:  # noqa: F811
    _set_pin(client)
    assert client.post("/api/settings/pin/check", json={"current_pin": PIN}).json() == {"ok": True}
    with session_scope() as session:
        assert load_settings(session).pin_configured is True


def test_a_wrong_pin_is_403_with_the_same_sentence_as_remove(client: TestClient) -> None:  # noqa: F811
    _set_pin(client)
    res = client.post("/api/settings/pin/check", json={"current_pin": "nope-nope"})
    assert res.status_code == 403
    assert res.json()["detail"] == "Current PIN is incorrect."


def test_a_padded_pin_is_422(client: TestClient) -> None:  # noqa: F811
    _set_pin(client)
    assert (
        client.post("/api/settings/pin/check", json={"current_pin": f" {PIN} "}).status_code == 422
    )
