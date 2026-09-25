"""PUT/POST /api/alerts/channels/telegram: malformed bot_token is a 422.

Purpose : Split out of test_routes_alerts.py (PRI rule 7's 300-line cap) so
          the shape-validation cases blind cap B2 added have their own home
          rather than pushing that file over the limit. The WhatsApp
          equivalent lives in test_routes_alerts_whatsapp.py, next to its
          other apikey/phone cases.
Constraints: Each case proves the malformed value never reaches the function
          that would build a live request, not just that the route answers
          422.
"""

from __future__ import annotations

from unittest.mock import MagicMock

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


def test_put_telegram_malformed_token_is_422_before_any_get_me_call(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    get_me_mock = MagicMock()
    monkeypatch.setattr("findplus.api.routes_alerts_telegram._get_me", get_me_mock)
    res = client.put("/api/alerts/channels/telegram", json={"bot_token": "bad"})
    assert res.status_code == 422
    get_me_mock.assert_not_called()


def test_setup_malformed_token_is_422_before_any_telegram_setup_call(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup_mock = MagicMock()
    monkeypatch.setattr("findplus.api.routes_alerts_telegram.telegram_setup", setup_mock)
    res = client.post("/api/alerts/channels/telegram/setup?wait=1", json={"bot_token": "tok"})
    assert res.status_code == 422
    setup_mock.assert_not_called()
