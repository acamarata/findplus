"""GET /api/status, /api/config and GET /api/icons; `_widget_state` unit
tests. Split from test_core_endpoints.py (E13 stage 2, size cap).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from findplus import honesty
from findplus.api._helpers import _widget_state


def test_status_new_fields(client: TestClient) -> None:
    body = client.get("/api/status").json()
    assert isinstance(body["provider_health"], list)
    assert isinstance(body["alerts_configured"], bool)
    assert isinstance(body["consecutive_failures"], int)
    assert body["last_error_type"] is None or isinstance(body["last_error_type"], str)


def test_config_notices(client: TestClient) -> None:
    notices = client.get("/api/config").json()["notices"]
    # The key set comes from honesty.NOTICES, never a retyped list: a later
    # ticket adding a sentence (chrome_required, the E8 alert notices) should
    # only have to edit honesty.py (R-P2-5).
    assert set(notices) == set(honesty.NOTICES)
    for value in notices.values():
        assert isinstance(value, str) and value
    assert notices["find_hub"] == honesty.FIND_HUB


@pytest.mark.parametrize(
    "error_type,failures,age_minutes,expected",
    [
        (None, 0, 1, "ok"),
        (None, 2, 1, "ok"),
        ("network", 0, 1, "ok"),
        ("auth", 0, 1, "error"),
        ("decrypt", 0, 1, "error"),
        (None, 3, 1, "error"),
        (None, 0, 11, "stale"),
        (None, 0, 9, "ok"),  # just inside 2 x the 5-minute interval
        # Both conditions true at once: api-contract.md orders error first.
        ("auth", 4, 60, "error"),
        (None, 4, 60, "error"),
        (None, None, None, "ok"),
    ],
)
def test_widget_state_priority(error_type, failures, age_minutes, expected) -> None:
    """`_widget_state` returns only ok|stale|error, error winning over stale."""
    last_poll_at = (
        None if age_minutes is None else datetime.now(UTC) - timedelta(minutes=age_minutes)
    )
    state = _widget_state(error_type, failures or 0, last_poll_at, 5 * 60)
    assert state == expected


def test_widget_state_never_returns_down() -> None:
    """`down` is rendered by the widget client on a connection failure (widget.md)."""
    for error_type in (None, "auth", "decrypt", "network", "down"):
        for failures in (0, 3, 99):
            assert _widget_state(error_type, failures, None, 300) in {"ok", "stale", "error"}


@pytest.mark.parametrize("error_type", ["AuthRequiredError", "DecryptionError", "unauthenticated"])
def test_widget_state_flags_the_error_types_the_poller_really_writes(error_type) -> None:
    """The widget must show `error` on the FIRST auth/decrypt failure.

    api-contract.md spells the trigger set `{auth, decrypt}`, but poller.py has
    never stored those two words — it stores the exception class name or the
    provider's verdict. Matching the spec's words alone meant a revoked Google
    session (the one failure a user must act on) read `ok` or `stale` until
    `consecutive_failures >= 3` finally fired, three poll cycles later.
    """
    assert _widget_state(error_type, 0, datetime.now(UTC), 5 * 60) == "error"


def test_error_state_types_covers_every_auth_or_decrypt_error_the_poller_stores() -> None:
    """Guard the coupling: poller.py is the only writer of `PollRun.error_type`.

    If a new auth/decrypt failure path adds another literal there, this test
    fails and ERROR_STATE_TYPES has to be widened with it, instead of the
    widget silently under-reporting again.
    """
    import re
    from pathlib import Path

    from findplus import poller
    from findplus.api._widget import ERROR_STATE_TYPES

    source = Path(poller.__file__).read_text(encoding="utf-8")
    literals = set(re.findall(r'error_type="([A-Za-z_]+)"', source))
    auth_or_decrypt = {name for name in literals if re.search(r"auth|decrypt", name, re.I)}
    assert auth_or_decrypt, "poller.py stores no auth/decrypt error_type literal any more"
    assert auth_or_decrypt <= ERROR_STATE_TYPES, sorted(auth_or_decrypt - ERROR_STATE_TYPES)


def test_get_icons_returns_49_pinned_ids(client: TestClient) -> None:
    """48 badge icons plus UAT2 U26's `bell` (the phone-tier tab bar)."""
    res = client.get("/api/icons")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 49
    assert all(row["id"].startswith("lucide:") and row["group"] for row in rows)


def test_get_icons_requires_unlock(locked_client: TestClient) -> None:
    assert locked_client.get("/api/icons").status_code == 401


def test_get_icons_missing_table(client, monkeypatch) -> None:
    from findplus import labels

    def raise_missing():
        raise RuntimeError("icon table missing; reinstall findplus")

    monkeypatch.setattr(labels, "lucide_subset", lambda: (_ for _ in ()).throw(raise_missing()))

    with pytest.raises(RuntimeError, match="icon table missing; reinstall findplus"):
        client.get("/api/icons")
