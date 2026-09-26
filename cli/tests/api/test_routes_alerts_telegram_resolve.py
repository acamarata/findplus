"""PUT /api/alerts/channels/telegram{,/targets}: `@name` resolution at save
time (WP1, gap-audit P12).

Split out of test_routes_alerts_telegram_targets.py (PRI rule-7 300-line
cap) -- that file keeps the plumbing tests (shape errors, cap, token never
touched); this one owns the Bot API resolution path itself. The Bot API is
mocked at telegram_targets.py's own httpx.Client/list_chats, never the
network (the autouse fixture would fail it anyway).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from findplus.alerts.store import AlertsChannels, TelegramCreds, save_alerts
from findplus.db.session import session_scope
from findplus.ingest import upsert_device

TOKEN = "9876543210:ABCdefGHIjklMNOpqrSTUvwxyz012345678"
_MOD = "findplus.alerts.channels.telegram_targets"


@pytest.fixture
def client(tmp_db):
    from findplus.api import create_app

    with session_scope() as session:
        upsert_device(session, "dev1", "Tag1")
    return TestClient(create_app())


def _seed_telegram(chat_ids=("1",), chat_labels=()):
    save_alerts(
        AlertsChannels(
            telegram=TelegramCreds(
                bot_token=TOKEN,
                chat_ids=chat_ids,
                chat_labels=chat_labels,
                chat_title="t",
                bot_username="b",
                captured_at="now",
            )
        )
    )


def test_put_targets_resolves_a_public_group_via_get_chat(client: TestClient) -> None:
    _seed_telegram()
    with patch(f"{_MOD}.httpx.Client") as mock_client:
        mock_client.return_value.get.return_value.status_code = 200
        mock_client.return_value.get.return_value.json.return_value = {
            "result": {"id": -100555, "type": "supergroup", "title": "Family"}
        }
        res = client.put("/api/alerts/channels/telegram/targets", json={"targets": "@family_group"})
    assert res.status_code == 200
    assert res.json()["telegram"]["targets"] == "-100555"


def test_put_targets_resolves_a_person_via_get_updates(client: TestClient) -> None:
    _seed_telegram()
    with (
        patch(f"{_MOD}.httpx.Client") as mock_client,
        patch(f"{_MOD}.list_chats") as mock_list_chats,
    ):
        mock_client.return_value.get.return_value.status_code = 400
        mock_list_chats.return_value = [
            {"id": "555", "type": "private", "title": "Alice", "username": "alice"}
        ]
        res = client.put("/api/alerts/channels/telegram/targets", json={"targets": "@alice"})
    assert res.status_code == 200
    assert res.json()["telegram"]["targets"] == "555"


def test_put_targets_unresolved_name_is_422_with_the_owner_facing_message(
    client: TestClient,
) -> None:
    _seed_telegram()
    with (
        patch(f"{_MOD}.httpx.Client") as mock_client,
        patch(f"{_MOD}.list_chats", return_value=[]),
    ):
        mock_client.return_value.get.return_value.status_code = 400
        res = client.put("/api/alerts/channels/telegram/targets", json={"targets": "@nobody_yet"})
    assert res.status_code == 422
    assert "@nobody_yet hasn't messaged your bot yet" in res.json()["detail"]
    assert "save again" in res.json()["detail"]


def test_put_targets_mixed_list_resolves_every_entry(client: TestClient) -> None:
    _seed_telegram()
    with (
        patch(f"{_MOD}.httpx.Client") as mock_client,
        patch(f"{_MOD}.list_chats") as mock_list_chats,
    ):
        mock_client.return_value.get.return_value.status_code = 400
        mock_list_chats.return_value = [{"id": "9", "type": "private", "username": "alice"}]
        res = client.put(
            "/api/alerts/channels/telegram/targets", json={"targets": "-100123, @alice, 555"}
        )
    assert res.status_code == 200
    assert res.json()["telegram"]["targets"] == "-100123,9,555"


def test_put_targets_webhook_conflict_during_resolution_maps_to_409(client: TestClient) -> None:
    _seed_telegram()
    with patch(f"{_MOD}.httpx.Client") as mock_client:
        mock_client.return_value.get.return_value.status_code = 409
        res = client.put("/api/alerts/channels/telegram/targets", json={"targets": "@some_bot"})
    assert res.status_code == 409


def test_put_channels_telegram_also_resolves_names(client: TestClient) -> None:
    """PUT /channels/telegram (the token-carrying route) resolves too, not
    just the token-free /targets sibling."""
    with (
        patch("findplus.api.routes_alerts_telegram._get_me", return_value={"username": "b"}),
        patch(f"{_MOD}.httpx.Client") as mock_client,
    ):
        mock_client.return_value.get.return_value.status_code = 200
        mock_client.return_value.get.return_value.json.return_value = {
            "result": {"id": -100555, "type": "supergroup", "title": "Family"}
        }
        res = client.put(
            "/api/alerts/channels/telegram",
            json={"bot_token": TOKEN, "targets": "@family_group"},
        )
    assert res.status_code == 200
    assert res.json()["telegram"]["targets"] == "-100555"
