"""The default arrive+leave rule per place and the "Notify me" backfill (spec § 5.3)."""

from __future__ import annotations

import types
from unittest.mock import patch

import pytest

from findplus.alerts.default_rules import choose_channels
from findplus.db.models_alerts import AlertRule
from findplus.db.session import session_scope

_TG = types.SimpleNamespace(bot_token="t", chat_ids=("1",))
_WEB = types.SimpleNamespace(url="https://example.invalid/hook", secret=None)
_WA = types.SimpleNamespace(phone="+15550000000", apikey="abcd")


def _cfg(telegram=None, webhook=None, whatsapp=None):
    return types.SimpleNamespace(telegram=telegram, webhook=webhook, whatsapp=whatsapp)


@pytest.mark.parametrize(
    ("cfg", "expected"),
    [
        (_cfg(), (["telegram"], False, "Connect Telegram to get these.")),
        (_cfg(whatsapp=_WA), (["whatsapp"], True, None)),
        (_cfg(webhook=_WEB), (["webhook"], True, None)),
        (_cfg(telegram=_TG, webhook=_WEB, whatsapp=_WA), (["telegram"], True, None)),
        (_cfg(webhook=_WEB, whatsapp=_WA), (["whatsapp", "webhook"], True, None)),
    ],
)
def test_default_rule_channels(session, cfg, expected):
    assert choose_channels(session, cfg) == expected


def test_native_when_the_desktop_app_has_shown_one(session):
    from datetime import UTC, datetime

    from findplus.db.models_alerts import AlertDelivery
    from tests.alerts._helpers import _rule, _seed_place_and_device

    _seed_place_and_device(session)
    rule = _rule()
    session.add(rule)
    session.flush()
    now = datetime.now(UTC)
    session.add(AlertDelivery(rule_id=rule.id, event_kind="device", event_id=1, sent_at=now,
                              status="delivered", channel="native", delivered_at=now))  # fmt: skip
    session.flush()
    assert choose_channels(session, _cfg()) == (["native"], True, None)


def _place(client, name, **extra):
    body = {"name": name, "latitude": 41.1, "longitude": -80.6, "radius_meters": 150, **extra}
    return client.post("/api/places", json=body)


def test_new_place_gets_arrive_and_leave_for_everyone(client):
    with patch("findplus.alerts.store.load_alerts", return_value=_cfg(telegram=_TG)):
        resp = _place(client, "Grandma's")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "family"
    rule = body["notify_rule"]
    assert rule["name"] == "Arrivals and departures at Grandma's"
    assert rule["channels"] == ["telegram"] and rule["enabled"] is True
    assert (rule["on_enter"], rule["on_exit"], rule["cooldown_minutes"]) == (True, True, 0)
    with session_scope() as s:
        row = s.query(AlertRule).one()
        assert row.all_people and row.group_id is None and row.device_id is None


def test_notify_false_adds_no_rule_and_kind_is_validated(client):
    resp = _place(client, "Shop", notify=False, kind="shop")
    assert resp.json()["notify_rule"] is None and resp.json()["kind"] == "shop"
    assert _place(client, "Moon", kind="moon").status_code == 422
    with session_scope() as s:
        assert s.query(AlertRule).count() == 0


def test_backfill_previews_then_adds_one_rule_per_uncovered_place(client):
    _place(client, "Home", notify=False)
    _place(client, "School", notify=False)
    with patch("findplus.alerts.store.load_alerts", return_value=_cfg()):
        _place(client, "Park")  # covered by its own (disabled) default rule
        dry = client.post("/api/places/notify-defaults?dry_run=true").json()
        assert dry["dry_run"] is True and dry["count"] == 2
        assert {r["place_name"] for r in dry["rules"]} == {"Home", "School"}
        assert dry["rules"][0]["hint"] == "Connect Telegram to get these."
        with session_scope() as s:
            assert s.query(AlertRule).count() == 1
        done = client.post("/api/places/notify-defaults").json()
    assert done["count"] == 2
    with session_scope() as s:
        assert s.query(AlertRule).count() == 3
    assert client.post("/api/places/notify-defaults?dry_run=1").json()["count"] == 0


def test_owner_picked_channel_wins_over_the_automatic_choice(session):
    cfg = _cfg(telegram=_TG, webhook=_WEB)
    assert choose_channels(session, cfg, ["webhook"]) == (["webhook"], True, None)
    assert choose_channels(session, cfg, ["webhook", "telegram"]) == (
        ["telegram", "webhook"],
        True,
        None,
    )


def test_picking_a_channel_that_is_not_connected_is_refused(session):
    with pytest.raises(ValueError, match="channel not connected: whatsapp"):
        choose_channels(session, _cfg(telegram=_TG), ["whatsapp"])


def test_place_api_uses_the_picked_channel_and_rolls_back_on_a_bad_one(client):
    cfg = _cfg(telegram=_TG, webhook=_WEB)
    with patch("findplus.alerts.store.load_alerts", return_value=cfg):
        ok = _place(client, "Pick Place", notify_channels=["webhook"])
        bad = _place(client, "Bad Pick Place", notify_channels=["whatsapp"])
    assert ok.status_code == 201 and ok.json()["notify_rule"]["channels"] == ["webhook"]
    assert bad.status_code == 422
    names = [p["name"] for p in client.get("/api/places").json()]
    assert "Bad Pick Place" not in names, "a refused channel must not leave a half-made place"
