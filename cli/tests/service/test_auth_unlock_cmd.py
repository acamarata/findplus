"""`findplus auth --unlock` (cli/cmd_auth_unlock.py): unlock encrypted locations.

Purpose    : The same job the dashboard uses, driven from a terminal: it opens
             Find+'s own Chrome window, waits for the Android screen lock, and
             stores the key. Prompts, progress, success and failure, with the
             job runner faked so no browser opens.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from findplus.cli.main import main
from findplus.providers.google_findhub import unlock as unlock_mod

SESSION = {"aas_token": "x", "username": "kid@example.com"}


def _sign_in(tmp_db, extra: dict | None = None) -> None:
    from findplus.config import get_settings

    settings = get_settings()
    settings.ensure_dirs()
    settings.secrets_file.write_text(json.dumps({**SESSION, **(extra or {})}))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    from findplus.cli import cmd_auth_unlock

    monkeypatch.setattr(cmd_auth_unlock.time, "sleep", lambda *_: None)


def _fake_job(monkeypatch, states):
    seq = iter(states)
    monkeypatch.setattr(unlock_mod, "start_google_unlock", lambda s: "job-1")
    monkeypatch.setattr(unlock_mod, "get_google_unlock_progress", lambda job_id: next(seq))
    monkeypatch.setattr(unlock_mod, "cancel_google_unlock", lambda job_id: True)


def test_unlock_runs_the_job_and_reports_success(tmp_db, monkeypatch) -> None:
    _sign_in(tmp_db)
    _fake_job(
        monkeypatch,
        [
            {"state": "waiting_for_user", "message": "Enter your Android phone's screen lock."},
            {"state": "done", "message": "Encrypted locations unlocked."},
        ],
    )
    result = CliRunner().invoke(main, ["auth", "--unlock"], input="y\n")
    assert result.exit_code == 0, result.output
    assert "Android phone's screen lock" in result.output
    assert "Encrypted locations unlocked." in result.output


def test_unlock_failure_exits_1_with_the_message(tmp_db, monkeypatch) -> None:
    _sign_in(tmp_db)
    _fake_job(
        monkeypatch, [{"state": "failed", "message": "The unlock did not finish. Try again."}]
    )
    result = CliRunner().invoke(main, ["auth", "--unlock"], input="y\n")
    assert result.exit_code == 1
    assert "did not finish" in result.output


def test_unlock_says_nothing_to_do_when_already_unlocked(tmp_db, monkeypatch) -> None:
    _sign_in(tmp_db, {"shared_key": "abcd"})
    started: list = []
    monkeypatch.setattr(unlock_mod, "start_google_unlock", lambda s: started.append(1))
    result = CliRunner().invoke(main, ["auth", "--unlock"])
    assert result.exit_code == 0
    assert "already unlocked" in result.output
    assert started == []


def test_unlock_requires_a_signed_in_account(tmp_db, monkeypatch) -> None:
    started: list = []
    monkeypatch.setattr(unlock_mod, "start_google_unlock", lambda s: started.append(1))
    result = CliRunner().invoke(main, ["auth", "--unlock"])
    assert result.exit_code == 0
    assert "Sign in to Google first" in result.output
    assert started == []
