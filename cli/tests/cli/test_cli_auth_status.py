"""`findplus auth --status [--json]`: the read-only half of the auth command.

The whole point of the flag is that it reports without doing anything, so the
third case patches both the Chrome job runner and `click.confirm` to raise.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from findplus.cli.main import main

STATUS = {
    "providers": [
        {
            "id": "google-find-hub",
            "signed_in": True,
            "account": "a@b.com",
            "method": "chrome",
            "last_checked": "2026-09-20T00:00:00+00:00",
            "needs": [],
        }
    ]
}

SIGNED_OUT = {
    "providers": [
        {
            "id": "apple-find-my",
            "signed_in": False,
            "account": None,
            "method": "apple-2fa",
            "last_checked": "2026-09-20T00:00:00+00:00",
            "needs": ["apple_extra"],
        }
    ]
}


@pytest.fixture
def status(monkeypatch):
    def _use(payload: dict) -> None:
        monkeypatch.setattr("findplus.providers.auth_status.build_auth_status", lambda: payload)

    return _use


def test_status_json_prints_the_exact_status_object(tmp_db, status) -> None:
    status(STATUS)
    result = CliRunner().invoke(main, ["auth", "--status", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == STATUS


def test_status_table_lists_provider_signed_in_account(tmp_db, status) -> None:
    status(STATUS)
    result = CliRunner().invoke(main, ["auth", "--status"])
    assert result.exit_code == 0, result.output
    assert "google-find-hub" in result.output
    assert "a@b.com" in result.output
    assert "yes" in result.output


def test_status_never_launches_chrome_or_prompts(tmp_db, status, monkeypatch) -> None:
    status(STATUS)
    monkeypatch.setattr(
        "findplus.providers.google_findhub.browser.start_google_auth",
        lambda settings: pytest.fail("start_google_auth must not be called by --status"),
    )
    monkeypatch.setattr("click.confirm", lambda *a, **k: pytest.fail("--status must not prompt"))

    result = CliRunner().invoke(main, ["auth", "--status"])

    assert result.exit_code == 0, result.output
    assert "Open Chrome and sign in now?" not in result.output


def test_a_signed_out_provider_shows_a_dash_not_none(tmp_db, status) -> None:
    status(SIGNED_OUT)
    result = CliRunner().invoke(main, ["auth", "--status"])
    assert result.exit_code == 0, result.output
    assert "-" in result.output
    assert "None" not in result.output
    assert "no" in result.output
