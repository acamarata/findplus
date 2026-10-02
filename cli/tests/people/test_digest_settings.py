"""The `people.digest` preference: GET/PATCH /api/settings, `findplus people digest`."""

from __future__ import annotations

import json
import threading

import pytest
from click.testing import CliRunner

from findplus.cli.main import main
from findplus.db.session import session_scope
from findplus.people import digest_prefs
from findplus.security import SessionStore
from findplus.service.digest import DigestScheduler
from findplus.state import set_setting

from ._digest_helpers import seed_school_day

DEFAULT = {"enabled": False, "time": "20:00", "people": [], "channel": "auto", "always_send": False}


def test_default_is_off(client):
    assert client.get("/api/settings").json()["people.digest"] == DEFAULT


def test_patch_merges_and_persists(client):
    (pid,) = seed_school_day()
    resp = client.patch("/api/settings", json={"people.digest": {"enabled": True, "time": "19:30"}})
    assert resp.status_code == 200, resp.text
    assert resp.json()["people.digest"] == {**DEFAULT, "enabled": True, "time": "19:30"}
    resp = client.patch("/api/settings", json={"people.digest": {"people": [pid, pid]}})
    assert resp.json()["people.digest"]["people"] == [pid]
    assert resp.json()["people.digest"]["enabled"] is True  # untouched keys stay
    assert client.get("/api/settings").json()["people.digest"]["time"] == "19:30"
    other = client.patch("/api/settings", json={"theme": "dark"})  # an unrelated PATCH keeps it
    assert other.json()["people.digest"]["enabled"] is True


@pytest.mark.parametrize(
    "bad",
    [
        {"time": "8pm"}, {"time": "24:00"}, {"time": 2000}, {"enabled": "yes"}, {"channel": "sms"},
        {"people": [9999]}, {"people": "all"}, {"people": [True]}, {"flavour": 1}, "on", None,
    ],
)  # fmt: skip
def test_bad_values_are_422_and_change_nothing(client, bad):
    seed_school_day()
    resp = client.patch("/api/settings", json={"people.digest": bad})
    assert resp.status_code == 422, resp.text
    assert client.get("/api/settings").json()["people.digest"] == DEFAULT


def test_a_damaged_stored_value_reads_as_the_default(tmp_db):
    with session_scope() as s:
        set_setting(s, digest_prefs.KEY, "{not json")
    with session_scope() as s:
        assert digest_prefs.load(s) == DEFAULT
        set_setting(s, digest_prefs.KEY, json.dumps({"enabled": True, "junk": 1}))
    with session_scope() as s:
        assert digest_prefs.load(s) == {**DEFAULT, "enabled": True}


def test_cli_shows_and_changes_the_digest(tmp_db):
    (pid,) = seed_school_day()
    run = CliRunner().invoke
    shown = run(main, ["people", "digest"])
    assert shown.exit_code == 0 and shown.output.strip() == (
        "Evening summary: off, 20:00, for everyone, via auto."
    )
    out = run(main, ["people", "digest", "--on", "--time", "19:30", "--person", "sam"])
    assert out.exit_code == 0, out.output
    assert out.output.strip() == "Evening summary: on, 19:30, for Sam, via auto."
    data = json.loads(run(main, ["people", "digest", "--json", "--always-send"]).output)
    assert data == {
        **DEFAULT,
        "enabled": True,
        "time": "19:30",
        "people": [pid],
        "always_send": True,
    }
    back = run(main, ["people", "digest", "--all-people", "--off", "--no-always-send"])
    assert "off, 19:30, for everyone" in back.output


def test_cli_digest_rejects_bad_input(tmp_db):
    seed_school_day()
    run = CliRunner().invoke
    assert run(main, ["people", "digest", "--time", "8pm"]).exit_code == 1
    ghost = run(main, ["people", "digest", "--person", "Nobody"])
    assert ghost.exit_code == 1 and "no person named" in ghost.output
    assert digest_prefs.DEFAULTS["enabled"] is False  # the shared defaults are never mutated


def test_serve_starts_the_digest_worker_beside_retention(tmp_db, monkeypatch):
    from findplus.cli import cmd_serve
    from findplus.config import get_settings

    started: dict = {}
    monkeypatch.setattr(
        cmd_serve, "_start_worker", lambda w, name: started.__setitem__(name, w) or (w, None)
    )
    monkeypatch.setattr(cmd_serve, "_stop_workers", lambda ws: None)
    seen: list = []

    class _Srv:
        should_exit = False

    def _fake_uvicorn(host, port, settings, sessions=None):
        seen.append(sessions)
        thread = threading.Thread(target=lambda: None)
        thread.start()
        return _Srv(), thread

    monkeypatch.setattr(cmd_serve, "_start_uvicorn", _fake_uvicorn)
    monkeypatch.setattr(cmd_serve, "_wait_for_stop", lambda ev, th: 0)
    cmd_serve._run_server(get_settings(), "127.0.0.1", 8999, True, threading.Event())
    assert {"retention", "digest"} <= set(started) and isinstance(
        started["digest"], DigestScheduler
    )
    assert isinstance(seen[0], SessionStore)  # the app keeps its own session store
