"""`findplus day`, the plain-text rendering, and the where_is / get_person_day MCP tools."""

from __future__ import annotations

import asyncio
import json

from click.testing import CliRunner

from findplus import honesty
from findplus.cli.main import main
from findplus.mcp.server import create_mcp_server
from findplus.people.day_render import render_text
from findplus.service import digest_send
from tests.mcp.test_server import StubClient

from ._digest_helpers import FakeChannel, connect_telegram, seed_school_day

ARGS = ["--date", "2026-09-21", "--timezone", "UTC"]


def run(*args):
    return CliRunner().invoke(main, ["day", *args])


def test_day_prints_the_lines_and_the_notices_once(tmp_db):
    seed_school_day()
    out = run("Sam", *ARGS)
    assert out.exit_code == 0, out.output
    lines = out.output.splitlines()
    assert lines[0] == "Sam's day, Mon Sep 21"
    assert any(x.startswith("- 8:10 AM arrived at School (") for x in lines)
    assert out.output.count(honesty.ALERTS_LATENCY) == 1
    assert out.output.count(honesty.TRIPS_APPROXIMATE) == 1


def test_day_json_is_the_api_shape_and_days_makes_a_list(tmp_db):
    seed_school_day()
    one = json.loads(run("sam", *ARGS, "--json").output)
    assert one["person"]["name"] == "Sam" and one["date"] == "2026-09-21"
    assert [x["text"] for x in one["lines"]][1] == "7:40 AM left Home"
    two = json.loads(run("Sam", *ARGS, "--days", "2", "--json").output)
    assert [d["date"] for d in two] == ["2026-09-21", "2026-09-22"]
    assert two[1]["empty"] is True
    text = run("Sam", *ARGS, "--days", "2").output
    assert "Sam's day, Tue Sep 22" in text and "No sightings for Sam on this day." in text
    assert text.count(honesty.TRIPS_APPROXIMATE) == 1


def test_day_resolves_names_and_refuses_unknown_or_ambiguous(tmp_db):
    (pid,) = seed_school_day()
    assert run(str(pid), *ARGS).exit_code == 0 and run("sa", *ARGS).exit_code == 0
    ghost = run("Nobody", *ARGS)
    assert ghost.exit_code == 1 and "no person named 'Nobody'" in ghost.output
    from findplus.db.session import session_scope
    from tests.people._helpers import seed_person

    with session_scope() as s:
        seed_person(s, "Samira", {"zn": "Samira"})
    both = run("sa", *ARGS)
    assert both.exit_code == 1 and "Sam, Samira" in both.output
    assert run("Sam", *ARGS).exit_code == 0  # the exact name still wins
    assert run("Sam", "--date", "tomorrow").exit_code == 1
    assert run("Sam", "--timezone", "Mars/Base").exit_code == 1


def test_day_send_goes_to_telegram_or_says_why_not(tmp_db, monkeypatch):
    seed_school_day()
    no_chat = run("Sam", *ARGS, "--send")
    assert no_chat.exit_code == 1 and "Telegram is not connected" in no_chat.output
    connect_telegram(("42", "43"))
    fake = FakeChannel()
    monkeypatch.setattr(digest_send, "default_sender", fake)
    ok = run("Sam", *ARGS, "--send")
    assert ok.exit_code == 0 and "Sent to 2 of 2 Telegram chat(s)." in ok.output
    assert [c for _, _, c in fake.sent] == ["42", "43"]
    fake.fail = 9
    bad = run("Sam", *ARGS, "--send")
    assert bad.exit_code == 1 and "HTTP 500" in bad.output and "AAAA" not in bad.output


def test_render_text_empty_and_without_notices():
    payload = {
        "person": {"id": 1, "name": "Robin"}, "date": "2026-09-21", "lines": [],
        "suspect_text": "2 sightings looked wrong and were left out.",
    }  # fmt: skip
    text = render_text(payload)
    assert text.splitlines()[:3] == [
        "Robin's day, Mon Sep 21",
        "",
        "No sightings for Robin on this day.",
    ]
    assert "2 sightings looked wrong" in text and honesty.ALERTS_LATENCY in text
    assert honesty.ALERTS_LATENCY not in render_text(payload, notices=False)


def _client(extra=None):
    base = {
        ("GET", "/api/config"): {"notices": {"find_hub": "NOTICE"}},
        ("GET", "/api/people"): [{"id": 1, "name": "Robin"}, {"id": 2, "name": "Robyn Lee"}],
        ("GET", "/api/people/1/now"): {"confidence": "likely", "text": "Likely at School"},
        ("GET", "/api/people/1/day"): {
            "person": {"id": 1},
            "lines": [{"text": "7:40 AM left Home"}],
        },
    }
    return StubClient({**base, **(extra or {})})


def _call(tool, args, client):
    mcp = create_mcp_server()
    mcp._daemon_client = client
    return asyncio.run(mcp.call_tool(tool, args)).structured_content


def test_mcp_where_is_and_get_person_day_carry_the_caveats():
    names = {t.name for t in asyncio.run(create_mcp_server().list_tools())}
    assert {"where_is", "get_person_day"} <= names
    now = _call("where_is", {"person": "robin"}, _client())
    assert now["text"] == "Likely at School"
    assert now["caveats"] == [honesty.PRESENCE_STALE, honesty.ALERTS_LATENCY]
    day = _call("get_person_day", {"person": "Robin", "date": "2026-09-21"}, _client())
    assert day["lines"][0]["text"] == "7:40 AM left Home"
    assert day["caveats"] == [
        honesty.PRESENCE_STALE,
        honesty.ALERTS_LATENCY,
        honesty.TRIPS_APPROXIMATE,
    ]
    by_id = _call("get_person_day", {"person": "1"}, _client())
    assert by_id["lines"]


def test_mcp_unknown_or_ambiguous_person_is_a_clean_error():
    missing = _call("where_is", {"person": "Nobody"}, _client())
    assert missing["error"]["code"] == "not_found" and "Robin" in missing["error"]["hint"]
    ambiguous = _call("get_person_day", {"person": "Rob"}, _client())
    assert ambiguous["error"]["code"] == "validation" and "caveats" not in ambiguous
    locked = _call(
        "where_is",
        {"person": "x"},
        StubClient(
            {
                ("GET", "/api/people"): {
                    "error": {
                        "code": "locked",
                        "message": "Find+ is locked",
                        "hint": "call unlock(pin)",
                    }
                }
            }
        ),
    )
    assert locked["error"]["code"] == "locked"
