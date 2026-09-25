# Purpose: Apple Find My account state: anisette provider selection, interactive
#          sign-in with 2FA, and session persistence.
# Inputs: findplus.config.Settings (state_dir, apple_anisette_url); interactive
#         prompts via click for Apple ID / password / 2FA code.
# Outputs: a findmy.AsyncAppleAccount, saved to and restored from
#          apple-account.json (0600).
# Constraints: no DB access (filesystem-only); no findmy import at module level
#              (this file must be importable without the optional `apple` extra
#              installed; is_available() gates every call site). FindMy.py's
#              to_json() includes the plaintext password; save_account() blanks
#              it, so the password is never written to disk.
from __future__ import annotations

import datetime
import json
import pathlib
from typing import Any

import click

from findplus.providers.apple_findmy.exceptions import AppleAuthRequiredError
from findplus.providers.apple_findmy.session import AppleSession, prepare_anisette

#: findmy.LoginState.LOGGED_IN.value, readable without importing findmy.
LOGGED_IN_VALUE = 3


def _state_path(settings) -> pathlib.Path:
    return pathlib.Path(settings.state_dir) / "apple-account.json"


def anisette_libs_path(settings) -> pathlib.Path:
    """Cache for the local anisette engine's libraries (a few MB, downloaded once)."""
    return pathlib.Path(settings.state_dir) / "anisette-libs.bin"


def make_anisette(settings):
    """The configured anisette provider: remote when a URL is set, else local.

    Neither constructor touches the network. The local one downloads its
    libraries on first use, which prepare_anisette() reports honestly.
    """
    import findmy

    if settings.apple_anisette_url:
        return findmy.RemoteAnisetteProvider(settings.apple_anisette_url)
    return findmy.LocalAnisetteProvider(libs_path=anisette_libs_path(settings))


def make_account(settings):
    """A fresh, logged-out findmy.AsyncAppleAccount on the configured anisette."""
    import findmy

    return findmy.AsyncAppleAccount(make_anisette(settings))


def account_state(account) -> dict[str, Any]:
    """account.to_json() with the password removed. Everything else is kept."""
    data = json.loads(json.dumps(account.to_json()))
    if isinstance(data.get("account"), dict):
        data["account"]["password"] = None
    return data


def read_saved_state(settings) -> dict[str, Any] | None:
    """The saved account mapping, or None when absent or unreadable."""
    path = _state_path(settings)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def is_signed_in(data: dict[str, Any] | None) -> bool:
    """True when a saved mapping records a completed (LOGGED_IN) sign-in."""
    login = (data or {}).get("login")
    return isinstance(login, dict) and login.get("state") == LOGGED_IN_VALUE


def save_account(account, settings) -> None:
    """Persist the account's session state (never the password) 0600."""
    path = _state_path(settings)
    path.parent.mkdir(mode=0o700, exist_ok=True)
    data = account_state(account)
    data["saved_at"] = datetime.datetime.now(tz=datetime.UTC).isoformat()
    # Narrow the mode BEFORE the session token is written: write_text() creates
    # the file 0644 under the usual umask, which would leave a window in which
    # another local user can read the token.
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text(json.dumps(data), encoding="utf-8")


def restore_account(settings):
    """Rebuild the saved, signed-in AsyncAppleAccount. No network.

    Raises AppleAuthRequiredError (never a raw findmy exception) when no saved
    session exists, when it cannot be parsed, or when it never finished
    signing in.
    """
    import findmy

    path = _state_path(settings)
    if not path.exists():
        raise AppleAuthRequiredError("run 'findplus auth --provider apple-find-my'")
    data = read_saved_state(settings)
    if not is_signed_in(data):
        raise AppleAuthRequiredError("Apple session expired: sign in again")
    try:
        return findmy.AsyncAppleAccount.from_json(
            data, anisette_libs_path=anisette_libs_path(settings)
        )
    except Exception as exc:
        raise AppleAuthRequiredError(f"Apple session expired: {exc}") from exc


def _choose_method(methods):
    """Show the second-factor methods Apple offered and return the chosen one."""
    click.echo("2FA required. Select a method by number:")
    for i, method in enumerate(methods, start=1):
        number = getattr(method, "phone_number", None)
        click.echo(f"  {i}) SMS to {number}" if number else f"  {i}) Trusted device")
    choices = [str(i) for i in range(1, len(methods) + 1)]
    return methods[int(click.prompt("Choice", type=click.Choice(choices))) - 1]


def sign_in_interactive(settings):
    """Prompt for Apple ID + password, handle 2FA, and save the resulting session.

    Boundary: a login() failure (bad credentials) is NOT wrapped; the raw
    findmy exception propagates so the caller sees the real cause.
    """
    import findmy

    account = make_account(settings)
    apple_id = click.prompt("Apple ID")
    password = click.prompt("Password", hide_input=True)
    with AppleSession(account) as session:
        prepare_anisette(session, settings)
        state = session.run(account.login(apple_id, password))
        if state == findmy.LoginState.REQUIRE_2FA:
            methods = list(session.run(account.get_2fa_methods()))
            if not methods:
                raise RuntimeError("Apple asked for a second factor but offered no usable method.")
            method = _choose_method(methods)
            session.run(method.request())
            state = session.run(method.submit(click.prompt("2FA code")))
        if state != findmy.LoginState.LOGGED_IN:
            raise RuntimeError(f"Apple sign-in did not finish (state {state}).")
        save_account(account, settings)
    return account
