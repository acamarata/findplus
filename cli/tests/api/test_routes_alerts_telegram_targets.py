"""PUT /api/alerts/channels/telegram/targets and GET .../updates ("Find chat
IDs"), plus the multi-target POST /api/alerts/test shape.

Purpose    : New in this ticket -- owner asked for a Telegram rule to accept
             a comma-separated list of targets (person/group/several people)
             and a "Find chat IDs" helper. Every Telegram Bot API call is
             mocked; no test here touches the network.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from findplus.alerts.store import AlertsChannels, TelegramCreds, save_alerts
from findplus.db.session import session_scope
from findplus.ingest import upsert_device

TOKEN = "9876543210:ABCdefGHIjklMNOpqrSTUvwxyz012345678"


@pytest.fixture
def client(tmp_db):
    from findplus.api import create_app

    with session_scope() as session:
        upsert_device(session, "dev1", "Tag1")
    return TestClient(create_app())


def _seed_telegram(chat_ids=("1",)):
    save_alerts(
        AlertsChannels(
            telegram=TelegramCreds(
                bot_token=TOKEN,
                chat_ids=chat_ids,
                chat_title="t",
                bot_username="b",
                captured_at="now",
            )
        )
    )


# --------------------------------------------------------- PUT .../targets
def test_put_targets_not_configured_is_422(client: TestClient) -> None:
    res = client.put("/api/alerts/channels/telegram/targets", json={"targets": "111"})
    assert res.status_code == 422


def test_put_targets_replaces_the_list(client: TestClient) -> None:
    """Pure numeric/negative ids need no Bot API call at all."""
    _seed_telegram()
    res = client.put("/api/alerts/channels/telegram/targets", json={"targets": "111, -100222"})
    assert res.status_code == 200
    assert res.json()["telegram"]["targets"] == "111,-100222"


def test_put_targets_bad_entry_is_422_naming_the_value(client: TestClient) -> None:
    _seed_telegram()
    res = client.put("/api/alerts/channels/telegram/targets", json={"targets": "111,not-a-target"})
    assert res.status_code == 422
    assert "not-a-target" in res.json()["detail"]


def test_put_targets_empty_is_422(client: TestClient) -> None:
    _seed_telegram()
    res = client.put("/api/alerts/channels/telegram/targets", json={"targets": " , "})
    assert res.status_code == 422


def test_put_targets_over_the_cap_is_422(client: TestClient) -> None:
    _seed_telegram()
    many = ",".join(str(n) for n in range(15))
    res = client.put("/api/alerts/channels/telegram/targets", json={"targets": many})
    assert res.status_code == 422


def test_put_targets_never_touches_the_bot_token(client: TestClient) -> None:
    _seed_telegram()
    res = client.put("/api/alerts/channels/telegram/targets", json={"targets": "111,222"})
    body = res.json()
    assert body["telegram"]["bot_username"] == "b"
    assert TOKEN not in res.text


# ------------------------------------------------- target_labels (UAT6 N15)
def test_channels_response_pairs_target_ids_with_labels(client: TestClient) -> None:
    """channels_response()'s target_ids/target_labels are the same list as
    the comma-joined `targets`, just not re-splittable-ambiguous -- the
    Alerts tab's chip row zips them by index (alerts_telegram_targets.js)."""
    from findplus.alerts.store import AlertsChannels, TelegramCreds, save_alerts

    save_alerts(
        AlertsChannels(
            telegram=TelegramCreds(
                bot_token=TOKEN,
                chat_ids=("1", "-100222", "3"),
                chat_labels=("@alice", "Family", ""),
                chat_title="t",
                bot_username="b",
                captured_at="now",
            )
        )
    )
    telegram = client.get("/api/alerts/channels").json()["telegram"]
    assert telegram["target_ids"] == ["1", "-100222", "3"]
    # The third target has no label (empty string) -- falls back to its id,
    # never a blank chip.
    assert telegram["target_labels"] == ["@alice", "Family", "3"]


def test_channels_response_target_labels_is_none_when_unconfigured(client: TestClient) -> None:
    telegram = client.get("/api/alerts/channels").json()["telegram"]
    assert telegram["target_ids"] is None
    assert telegram["target_labels"] is None


# --------------------------------------------------------- GET .../updates
def test_get_updates_not_configured_is_422(client: TestClient) -> None:
    res = client.get("/api/alerts/channels/telegram/updates")
    assert res.status_code == 422


def test_get_updates_returns_distinct_chats(client: TestClient) -> None:
    _seed_telegram()
    chats = [
        {"id": "1", "type": "private", "title": "Alice", "username": "alice"},
        {"id": "-100222", "type": "supergroup", "title": "Family", "username": None},
    ]
    with patch("findplus.api.routes_alerts_telegram.list_chats", return_value=chats) as mock:
        res = client.get("/api/alerts/channels/telegram/updates")
    assert res.status_code == 200
    assert res.json() == {"chats": chats}
    mock.assert_called_once_with(TOKEN)


def test_get_updates_no_updates_yet_is_an_empty_list_not_an_error(client: TestClient) -> None:
    _seed_telegram()
    with patch("findplus.api.routes_alerts_telegram.list_chats", return_value=[]):
        res = client.get("/api/alerts/channels/telegram/updates")
    assert res.status_code == 200
    assert res.json() == {"chats": []}


def test_get_updates_never_returns_the_token(client: TestClient) -> None:
    _seed_telegram()
    chats = [{"id": "1", "type": "private", "title": "Alice", "username": "alice"}]
    with patch("findplus.api.routes_alerts_telegram.list_chats", return_value=chats):
        res = client.get("/api/alerts/channels/telegram/updates")
    assert TOKEN not in res.text


def test_get_updates_invalid_token_maps_to_400(client: TestClient) -> None:
    _seed_telegram()
    with patch(
        "findplus.api.routes_alerts_telegram.list_chats",
        side_effect=ValueError("telegram: invalid token (401)"),
    ):
        res = client.get("/api/alerts/channels/telegram/updates")
    assert res.status_code == 400


def test_get_updates_webhook_conflict_maps_to_409(client: TestClient) -> None:
    _seed_telegram()
    with patch(
        "findplus.api.routes_alerts_telegram.list_chats",
        side_effect=RuntimeError("telegram: a webhook is set on this bot"),
    ):
        res = client.get("/api/alerts/channels/telegram/updates")
    assert res.status_code == 409


# --------------------------------------------------------- multi-target test
def test_test_endpoint_reports_per_target_results(client: TestClient) -> None:
    _seed_telegram(chat_ids=("good", "bad"))

    def _send(text, bot_token, chat_id, **kw):
        if chat_id == "bad":
            return MagicMock(success=False, error="blocked")
        return MagicMock(success=True, error=None)

    with patch("findplus.api.routes_alerts_telegram.send", side_effect=_send):
        res = client.post("/api/alerts/test", json={"channel": "telegram"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "partial"
    assert body["error"] == "blocked"
    by_target = {r["target"]: r for r in body["results"]}
    assert by_target["good"]["status"] == "sent"
    assert by_target["bad"]["status"] == "failed"
    assert by_target["bad"]["error"] == "blocked"


def test_test_endpoint_all_targets_sent_is_overall_sent(client: TestClient) -> None:
    _seed_telegram(chat_ids=("a", "b"))
    with patch(
        "findplus.api.routes_alerts_telegram.send",
        return_value=MagicMock(success=True, error=None),
    ):
        res = client.post("/api/alerts/test", json={"channel": "telegram"})
    body = res.json()
    assert body["status"] == "sent"
    assert body["error"] is None
    assert len(body["results"]) == 2


def test_test_endpoint_no_targets_configured_is_422(client: TestClient) -> None:
    _seed_telegram(chat_ids=())
    res = client.post("/api/alerts/test", json={"channel": "telegram"})
    assert res.status_code == 422


# ------------------------------------- rule pruning (WP10, gap-audit P13)
def _rule_with_targets(client: TestClient, targets: list[str]) -> int:
    return client.post(
        "/api/alerts/rules",
        json={
            "name": "r1",
            "device_id": "dev1",
            "channels": ["telegram"],
            "telegram_targets": targets,
        },
    ).json()["id"]


def test_put_targets_drops_a_removed_id_from_a_rules_subset(client: TestClient) -> None:
    _seed_telegram(chat_ids=("1", "2"))
    rule_id = _rule_with_targets(client, ["1", "2"])
    res = client.put("/api/alerts/channels/telegram/targets", json={"targets": "2"})
    assert res.status_code == 200
    rule = client.get("/api/alerts/rules").json()[0]
    assert rule["id"] == rule_id
    assert rule["telegram_targets"] == ["2"]


def test_put_targets_collapses_a_rule_to_explicit_empty_when_its_whole_subset_is_removed(
    client: TestClient,
) -> None:
    _seed_telegram(chat_ids=("1", "2"))
    _rule_with_targets(client, ["1"])
    client.put("/api/alerts/channels/telegram/targets", json={"targets": "2"})
    rule = client.get("/api/alerts/rules").json()[0]
    assert rule["telegram_targets"] == []


def test_put_targets_never_touches_a_rule_left_at_null_every_target(client: TestClient) -> None:
    _seed_telegram(chat_ids=("1", "2"))
    client.post(
        "/api/alerts/rules", json={"name": "r1", "device_id": "dev1", "channels": ["telegram"]}
    )
    client.put("/api/alerts/channels/telegram/targets", json={"targets": "2"})
    assert client.get("/api/alerts/rules").json()[0]["telegram_targets"] is None


def test_delete_telegram_collapses_every_narrowed_rule_to_explicit_empty(
    client: TestClient,
) -> None:
    _seed_telegram(chat_ids=("1", "2"))
    _rule_with_targets(client, ["1"])
    assert client.delete("/api/alerts/channels/telegram").status_code == 204
    assert client.get("/api/alerts/rules").json()[0]["telegram_targets"] == []


def test_put_telegram_full_resave_also_prunes_rules(client: TestClient) -> None:
    """PUT /channels/telegram (reconnecting with a fresh, narrower target
    list) prunes the same way PUT .../targets does -- both go through
    put_telegram's own `_prune_rules_to`."""
    _seed_telegram(chat_ids=("1", "2"))
    rule_id = _rule_with_targets(client, ["1", "2"])
    with patch("findplus.api.routes_alerts_telegram._get_me", return_value={"username": "b"}):
        res = client.put("/api/alerts/channels/telegram", json={"bot_token": TOKEN, "targets": "2"})
    assert res.status_code == 200
    rule = client.get("/api/alerts/rules").json()[0]
    assert rule["id"] == rule_id
    assert rule["telegram_targets"] == ["2"]
