"""`findplus auth` leads with the Find+ helper route (cli/cmd_auth_helper.py).

Purpose    : in a terminal with the service running, `auth` offers the helper
             route first: it asks the daemon to begin, prints the begin address,
             waits for a NEW sign-in generation and reports the account. A
             failure, a timeout, a declined prompt or a missing daemon falls
             through to the separate-window flow. Scripts (no tty) keep the old
             flow unless --helper is given. The daemon is faked; nothing opens.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from findplus.cli import cmd_auth_helper as ch
from findplus.cli.main import main

BEGIN_URL = "http://127.0.0.1:8647/auth/google/begin?state=abc"


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(ch.time, "sleep", lambda *_: None)
    monkeypatch.setattr("webbrowser.open", lambda url: None)


def _status(generation=0, account="old@example.com", outcome=None, seen=True):
    return {
        "providers": [{"id": ch.PROVIDER_ID, "signed_in": True, "account": account, "needs": []}],
        "google_helper_installed": seen,
        "google_signin_generation": generation,
        "google_helper_outcome": outcome,
    }


def _fake_daemon(monkeypatch, statuses, begin=None):
    seq = iter(statuses)
    last = {}

    def get_status(base):
        last["v"] = next(seq, last.get("v"))
        return last["v"]

    monkeypatch.setattr(ch, "_daemon_status", get_status)
    monkeypatch.setattr(
        ch,
        "_begin",
        lambda base: begin if begin is not None else {"url": BEGIN_URL, "generation": 3},
    )


def _fallback(monkeypatch):
    called = []
    monkeypatch.setattr(
        "findplus.cli.cmd_auth._auth_google_automated", lambda p, s: called.append(1)
    )
    return called


def test_helper_route_waits_for_a_new_generation_then_reports_the_account(tmp_db, monkeypatch):
    # first call: availability probe; then two polls of the OLD sign-in, then the new one
    _fake_daemon(
        monkeypatch,
        [_status(3), _status(3), _status(3), _status(4, "new@example.com")],
    )
    fallback = _fallback(monkeypatch)
    result = CliRunner().invoke(main, ["auth", "--helper"], input="y\n")
    assert result.exit_code == 0, result.output
    assert BEGIN_URL in result.output
    assert "Authenticated as new@example.com" in result.output
    assert "old@example.com" not in result.output
    assert fallback == []


def test_a_reported_failure_falls_back_to_the_separate_window(tmp_db, monkeypatch):
    failed = {"kind": "signin", "ok": False, "message": "Couldn't reach Google."}
    _fake_daemon(monkeypatch, [_status(3), _status(3, outcome=failed)])
    fallback = _fallback(monkeypatch)
    result = CliRunner().invoke(main, ["auth", "--helper"], input="y\n")
    assert "Couldn't reach Google." in result.output
    assert fallback == [1]


def test_declining_the_prompt_uses_the_separate_window(tmp_db, monkeypatch):
    _fake_daemon(monkeypatch, [_status(3)])
    fallback = _fallback(monkeypatch)
    CliRunner().invoke(main, ["auth", "--helper"], input="n\n")
    assert fallback == [1]


def test_no_daemon_falls_back_and_says_why(tmp_db, monkeypatch):
    monkeypatch.setattr(ch, "_daemon_status", lambda base: None)
    fallback = _fallback(monkeypatch)
    result = CliRunner().invoke(main, ["auth", "--helper"])
    assert "needs the Find+ service running" in result.output
    assert fallback == [1]


def test_timeout_falls_back(tmp_db, monkeypatch):
    monkeypatch.setattr(ch, "WAIT_SECONDS", 0.0)
    _fake_daemon(monkeypatch, [_status(3)])
    fallback = _fallback(monkeypatch)
    result = CliRunner().invoke(main, ["auth", "--helper"], input="y\n")
    assert "did not finish in 5 minutes" in result.output
    assert fallback == [1]


def test_without_a_terminal_the_helper_is_skipped_unless_asked(tmp_db, monkeypatch):
    called = []
    monkeypatch.setattr(ch, "auth_google_helper", lambda s: called.append(1) or True)
    fallback = _fallback(monkeypatch)
    CliRunner().invoke(main, ["auth"])  # CliRunner stdin is not a tty
    assert called == [] and fallback == [1]


def test_no_helper_skips_it_even_on_a_terminal(tmp_db, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    called = []
    monkeypatch.setattr(ch, "auth_google_helper", lambda s: called.append(1) or True)
    fallback = _fallback(monkeypatch)
    CliRunner().invoke(main, ["auth", "--no-helper"])
    assert called == [] and fallback == [1]
