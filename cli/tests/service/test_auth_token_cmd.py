"""`findplus auth --token` (cli/cmd_auth_token.py): Google sign-in from your own Chrome.

Purpose    : The same exchange the dashboard's main-Chrome flow runs, from a
             terminal: prompts (token hidden) or FINDPLUS_OAUTH_TOKEN, a plain
             failure message and exit 1, and the token never printed.
Constraints: gpsoauth and FcmReceiver are faked; the autouse no_real_browser
             guard stands in for Chrome. No network, no real ~/.findplus.
"""

from __future__ import annotations

from click.testing import CliRunner

from findplus.cli.main import main
from findplus.providers.google_findhub import token_signin
from findplus.providers.google_findhub.open_signin import EMBEDDED_SETUP_URL
from tests.providers._google_token_helpers import (
    AAS,
    EMAIL,
    TOKEN,
    install_google_fakes,
    isolate_store,
    read_store,
)


def test_prompts_open_chrome_and_sign_in(tmp_db, monkeypatch, no_real_browser) -> None:
    monkeypatch.delenv("FINDPLUS_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(
        "findplus.providers.google_findhub.open_signin.find_google_chrome", lambda: "/x/chrome"
    )
    store = isolate_store(monkeypatch)
    calls = install_google_fakes(monkeypatch)

    result = CliRunner().invoke(main, ["auth", "--token"], input=f"y\n{EMAIL}\n{TOKEN}\n")

    assert result.exit_code == 0, result.output
    assert no_real_browser == [EMBEDDED_SETUP_URL]
    assert "Option+Command+I" in result.output and "oauth_token" in result.output
    assert f"Authenticated as {EMAIL}." in result.output
    assert TOKEN not in result.output  # hidden input: the prompt never echoes it
    assert calls[0][:2] == (EMAIL, TOKEN)
    assert read_store(store)["aas_token"] == AAS


def test_the_token_can_come_from_the_environment(tmp_db, monkeypatch, no_real_browser) -> None:
    monkeypatch.setenv("FINDPLUS_OAUTH_TOKEN", f"  {TOKEN}\n")
    isolate_store(monkeypatch)
    calls = install_google_fakes(monkeypatch)

    result = CliRunner().invoke(main, ["auth", "--token"], input=f"{EMAIL}\n")

    assert result.exit_code == 0, result.output
    assert "oauth_token value" not in result.output  # no token prompt
    assert no_real_browser == []  # nothing to open: the token is already in hand
    assert calls[0][:2] == (EMAIL, TOKEN)


def test_a_rejected_token_exits_1_with_the_plain_message(tmp_db, monkeypatch) -> None:
    monkeypatch.setenv("FINDPLUS_OAUTH_TOKEN", TOKEN)
    store = isolate_store(monkeypatch)
    install_google_fakes(monkeypatch, response={"Error": "BadAuthentication"})

    result = CliRunner().invoke(main, ["auth", "--token"], input=f"{EMAIL}\n")

    assert result.exit_code == 1
    assert token_signin.MSG_REJECTED in result.output
    assert TOKEN not in result.output
    assert "aas_token" not in read_store(store)


def test_a_malformed_token_is_refused_before_google_is_asked(tmp_db, monkeypatch) -> None:
    monkeypatch.setenv("FINDPLUS_OAUTH_TOKEN", "ya29.not-the-cookie")
    isolate_store(monkeypatch)
    calls = install_google_fakes(monkeypatch)

    result = CliRunner().invoke(main, ["auth", "--token"], input=f"{EMAIL}\n")

    assert result.exit_code == 1
    assert "starts with oauth2_4/" in result.output
    assert calls == []
