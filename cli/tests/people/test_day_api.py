"""GET /api/people/{id}/day and POST /api/people/{id}/day/send (spec § 7.2)."""

from __future__ import annotations

from findplus import honesty
from findplus.service import digest_send

from ._digest_helpers import FakeChannel, connect_telegram, seed_school_day

DAY = {"date": "2026-09-21", "timezone": "UTC"}
LINES = [
    "Overnight at Home",
    "7:40 AM left Home",
    "8:10 AM arrived at School",
    "3:00 PM left School",
    "At Home from 3:33 PM",
]


def test_day_shape_and_lines(client):
    (pid,) = seed_school_day()
    resp = client.get(f"/api/people/{pid}/day", params=DAY)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {
        "person", "date", "timezone", "now", "heading", "lines", "left_behind", "suspect_count",
        "suspect_text", "gaps", "trackers", "lead_device_id", "empty", "label",
    }  # fmt: skip
    assert body["person"] == {"id": pid, "name": "Sam"} and body["date"] == "2026-09-21"
    assert body["timezone"] == "UTC" and body["now"] is None  # a past day has no "now"
    assert [x["text"] for x in body["lines"]] == LINES
    assert body["label"] == honesty.TRIPS_APPROXIMATE
    line = body["lines"][1]
    assert set(line) == {
        "kind", "at", "at_local", "end", "end_local", "time", "text", "via", "evidence",
        "confidence", "approximate", "place_id", "place_name", "latitude", "longitude",
    }  # fmt: skip
    assert line["at"] == "2026-09-21T07:40:00Z" and line["time"] == "7:40 AM"
    assert line["evidence"] and line["approximate"] is False
    assert {t["device_id"] for t in body["trackers"]} == {"zb", "zk", "zr", "zw"}


def test_today_carries_the_now_answer(client):
    (pid,) = seed_school_day()
    body = client.get(f"/api/people/{pid}/day", params={"timezone": "UTC"}).json()
    assert body["date"] != "2026-09-21"  # real "today": the old sightings are stale
    assert body["now"] is not None and body["now"]["confidence"] == "unknown"
    assert body["empty"] is True and body["lines"] == []


def test_day_errors(client):
    (pid,) = seed_school_day()
    assert client.get(f"/api/people/{pid}/day", params={"date": "yesterday"}).status_code == 400
    assert client.get(f"/api/people/{pid}/day", params={"timezone": "Mars/Base"}).status_code == 400
    assert client.get("/api/people/9999/day", params=DAY).status_code == 404
    group = client.post("/api/groups", json={"name": "Kids", "member_ids": []}).json()["id"]
    assert client.get(f"/api/people/{group}/day", params=DAY).status_code == 404  # a set


def test_send_needs_a_connected_chat(client):
    (pid,) = seed_school_day()
    resp = client.post(f"/api/people/{pid}/day/send", json=DAY)
    assert resp.status_code == 409 and "Connect Telegram" in resp.json()["detail"]


def test_send_posts_a_clean_list_with_the_notices_once(client, monkeypatch):
    (pid,) = seed_school_day()
    connect_telegram(("42", "@family_chat"))
    fake = FakeChannel()
    monkeypatch.setattr(digest_send, "default_sender", fake)
    resp = client.post(f"/api/people/{pid}/day/send", json=DAY)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sent"] is True and body["channel"] == "telegram"
    assert [t["target"] for t in body["targets"]] == ["42", "@family_chat"]
    assert [c for _, _, c in fake.sent] == ["42", "@family_chat"]
    text = fake.sent[0][0]
    assert text == body["text"]
    head, *rest = text.split("\n")
    assert head == "Sam's day, Mon Sep 21" and rest[0] == ""
    assert rest[1].startswith("- Overnight at Home (") and rest[1].endswith(" more)")
    assert any(x.startswith("- 7:40 AM left Home (") for x in rest)
    assert text.count(honesty.ALERTS_LATENCY) == 1 and text.count(honesty.TRIPS_APPROXIMATE) == 1
    assert text.endswith(honesty.TRIPS_APPROXIMATE)
    assert "**" not in text and "<" not in text  # plain text, nothing for Telegram to mangle


def test_send_failure_is_a_502_without_the_token(client, monkeypatch):
    (pid,) = seed_school_day()
    connect_telegram()
    monkeypatch.setattr(digest_send, "default_sender", FakeChannel(fail=9))
    resp = client.post(f"/api/people/{pid}/day/send", json=DAY)
    assert resp.status_code == 502 and "HTTP 500" in resp.json()["detail"]
    assert "AAAA" not in resp.text


def test_send_with_one_dead_chat_still_succeeds(client, monkeypatch):
    (pid,) = seed_school_day()
    connect_telegram(("42", "43"))
    monkeypatch.setattr(digest_send, "default_sender", FakeChannel(fail=1))
    body = client.post(f"/api/people/{pid}/day/send", json=DAY).json()
    assert [t["ok"] for t in body["targets"]] == [False, True]


def test_day_routes_401_while_locked_and_leak_nothing(locked_client):
    for method, path in (
        ("get", "/api/people/1/day"),
        ("post", "/api/people/1/day/send"),
        ("get", "/api/settings"),
    ):
        resp = getattr(locked_client, method)(path)
        assert resp.status_code == 401, (path, resp.status_code)
        assert "Sam" not in resp.text and "people.digest" not in resp.text
