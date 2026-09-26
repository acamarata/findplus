"""RuleCreate/RuleUpdate `telegram_targets` (WP10, gap-audit P13): a rule can
narrow Telegram delivery to a subset of the account's saved chat ids.

Purpose : None (the default, "every saved target"), an explicit subset, and
          an explicit empty list must all round-trip through POST/PUT/GET
          exactly, and an id that is not one of the saved targets must be
          rejected with a 422 naming it -- never silently dropped or stored.
"""

from __future__ import annotations

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


def _seed_telegram(chat_ids=("1", "2", "3")) -> None:
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


def test_create_without_telegram_targets_defaults_to_null_every_target(client: TestClient) -> None:
    res = client.post(
        "/api/alerts/rules", json={"name": "r1", "device_id": "dev1", "channels": ["native"]}
    )
    assert res.status_code == 201
    assert res.json()["telegram_targets"] is None


def test_create_with_a_saved_subset_round_trips(client: TestClient) -> None:
    _seed_telegram()
    res = client.post(
        "/api/alerts/rules",
        json={
            "name": "r1",
            "device_id": "dev1",
            "channels": ["telegram"],
            "telegram_targets": ["2"],
        },
    )
    assert res.status_code == 201
    assert res.json()["telegram_targets"] == ["2"]


def test_create_with_an_explicit_empty_list_round_trips(client: TestClient) -> None:
    """Distinct from omitting the field: the owner picked no chat at all."""
    _seed_telegram()
    res = client.post(
        "/api/alerts/rules",
        json={
            "name": "r1",
            "device_id": "dev1",
            "channels": ["telegram"],
            "telegram_targets": [],
        },
    )
    assert res.status_code == 201
    assert res.json()["telegram_targets"] == []


def test_create_rejects_a_target_that_is_not_saved(client: TestClient) -> None:
    _seed_telegram(chat_ids=("1",))
    res = client.post(
        "/api/alerts/rules",
        json={
            "name": "bad",
            "device_id": "dev1",
            "channels": ["telegram"],
            "telegram_targets": ["999"],
        },
    )
    assert res.status_code == 422
    assert "999" in res.json()["detail"][0]["msg"]


def test_create_rejects_a_target_when_telegram_is_not_even_configured(client: TestClient) -> None:
    res = client.post(
        "/api/alerts/rules",
        json={
            "name": "bad",
            "device_id": "dev1",
            "channels": ["native"],
            "telegram_targets": ["1"],
        },
    )
    assert res.status_code == 422


def test_put_narrows_an_existing_rule_to_a_subset(client: TestClient) -> None:
    _seed_telegram()
    rule_id = client.post(
        "/api/alerts/rules", json={"name": "r1", "device_id": "dev1", "channels": ["telegram"]}
    ).json()["id"]
    res = client.put(f"/api/alerts/rules/{rule_id}", json={"telegram_targets": ["1", "3"]})
    assert res.status_code == 200
    assert res.json()["telegram_targets"] == ["1", "3"]


def test_put_resets_a_narrowed_rule_back_to_null_every_target(client: TestClient) -> None:
    _seed_telegram()
    rule_id = client.post(
        "/api/alerts/rules",
        json={
            "name": "r1",
            "device_id": "dev1",
            "channels": ["telegram"],
            "telegram_targets": ["1"],
        },
    ).json()["id"]
    res = client.put(f"/api/alerts/rules/{rule_id}", json={"telegram_targets": None})
    assert res.status_code == 200
    assert res.json()["telegram_targets"] is None


def test_put_omitting_the_field_leaves_the_existing_subset_untouched(client: TestClient) -> None:
    _seed_telegram()
    rule_id = client.post(
        "/api/alerts/rules",
        json={
            "name": "r1",
            "device_id": "dev1",
            "channels": ["telegram"],
            "telegram_targets": ["2"],
        },
    ).json()["id"]
    res = client.put(f"/api/alerts/rules/{rule_id}", json={"cooldown_minutes": 5})
    assert res.status_code == 200
    assert res.json()["telegram_targets"] == ["2"]
    assert res.json()["cooldown_minutes"] == 5


def test_put_rejects_an_unsaved_target_without_touching_the_rule(client: TestClient) -> None:
    _seed_telegram()
    rule_id = client.post(
        "/api/alerts/rules",
        json={
            "name": "keepme",
            "device_id": "dev1",
            "channels": ["telegram"],
            "telegram_targets": ["2"],
        },
    ).json()["id"]
    res = client.put(f"/api/alerts/rules/{rule_id}", json={"telegram_targets": ["nope"]})
    assert res.status_code == 422
    assert client.get("/api/alerts/rules").json()[0]["telegram_targets"] == ["2"]
