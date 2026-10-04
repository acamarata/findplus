"""The current-PIN checks are throttled like the unlock itself (O20).

POST /api/settings/pin/check, the change (POST /pin) and the remove (DELETE /pin)
all answer "is this the PIN?", so each is a guessing oracle for anyone holding an
unlocked session. They share SessionStore's escalating lockout with /api/unlock:
five wrong PINs, then 429 with the wait, doubling each time.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from findplus.security import MAX_ATTEMPTS
from tests.api._lock_helpers import PIN, _set_pin, client, store  # noqa: F401

CHECK = "/api/settings/pin/check"


def _wrong(client: TestClient, n: int) -> None:  # noqa: F811
    for _ in range(n):
        assert client.post(CHECK, json={"current_pin": "wrong-pin"}).status_code == 403


def test_five_wrong_checks_then_429_with_the_wait(client: TestClient) -> None:  # noqa: F811
    _set_pin(client)
    _wrong(client, MAX_ATTEMPTS)
    res = client.post(CHECK, json={"current_pin": "wrong-pin"})
    assert res.status_code == 429
    assert "Try again in" in res.json()["detail"]


def test_the_right_pin_is_refused_too_while_locked_out(client: TestClient) -> None:  # noqa: F811
    _set_pin(client)
    _wrong(client, MAX_ATTEMPTS)
    assert client.post(CHECK, json={"current_pin": PIN}).status_code == 429


def test_a_few_typos_then_the_right_pin_pays_nothing(client: TestClient) -> None:  # noqa: F811
    _set_pin(client)
    _wrong(client, MAX_ATTEMPTS - 1)
    assert client.post(CHECK, json={"current_pin": PIN}).json() == {"ok": True}
    _wrong(client, MAX_ATTEMPTS - 1)  # the right PIN cleared the count


def test_the_lockout_is_shared_with_remove_and_change(client: TestClient) -> None:  # noqa: F811
    _set_pin(client)
    _wrong(client, MAX_ATTEMPTS)
    removed = client.request("DELETE", "/api/settings/pin", json={"current_pin": PIN})
    assert removed.status_code == 429
    changed = client.post("/api/settings/pin", json={"new_pin": "another-pin", "current_pin": PIN})
    assert changed.status_code == 429


def test_wrong_pins_on_remove_count_toward_the_lockout(client: TestClient) -> None:  # noqa: F811
    _set_pin(client)
    for _ in range(MAX_ATTEMPTS):
        res = client.request("DELETE", "/api/settings/pin", json={"current_pin": "wrong-pin"})
        assert res.status_code == 403
    assert client.post(CHECK, json={"current_pin": PIN}).status_code == 429


def test_no_pin_set_means_nothing_to_throttle(client: TestClient) -> None:  # noqa: F811
    for _ in range(MAX_ATTEMPTS + 2):
        assert client.post(CHECK, json={"current_pin": "whatever-1"}).status_code == 200
