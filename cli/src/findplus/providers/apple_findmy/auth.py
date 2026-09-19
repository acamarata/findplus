# Purpose: Apple Find My account state — anisette provider selection, interactive
#          sign-in with 2FA, and session persistence.
# Inputs: findplus.config.Settings (state_dir, apple_anisette_url); interactive
#         prompts via click for Apple ID / password / 2FA code.
# Outputs: a findmy.AppleAccount, saved to and restored from apple-account.json.
# Constraints: no DB access (filesystem-only); no findmy import at module level
#              (this file must be importable without the optional `apple` extra
#              installed — is_available() gates every call site); the Apple ID
#              and password are never persisted, only account.to_json() state.
from __future__ import annotations

import datetime
import json
import pathlib

import click

from findplus.providers.apple_findmy.exceptions import AppleAuthRequiredError


def make_account(settings):
    """Build a findmy.AppleAccount using the configured anisette provider.

    A remote anisette-server URL (settings.apple_anisette_url) is preferred when
    set; otherwise FindMy.py's LocalAnisetteProvider runs a local anisette
    daemon. Imports findmy lazily so this module loads without the extra.
    """
    import findmy
    import findmy.auth

    provider = (
        findmy.auth.RemoteAnisetteProvider(settings.apple_anisette_url)
        if settings.apple_anisette_url
        else findmy.auth.LocalAnisetteProvider()
    )
    return findmy.AppleAccount(provider)


def _state_path(settings) -> pathlib.Path:
    return pathlib.Path(settings.state_dir) / "apple-account.json"


def save_account(account, settings) -> None:
    """Persist the account's opaque session state (never credentials) 0600."""
    path = _state_path(settings)
    path.parent.mkdir(mode=0o700, exist_ok=True)
    data = account.to_json()
    data["saved_at"] = datetime.datetime.now(tz=datetime.UTC).isoformat()
    # Narrow the mode BEFORE the session token is written: write_text() creates
    # the file 0644 under the usual umask, which would leave a window in which
    # another local user can read the token.
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text(json.dumps(data), encoding="utf-8")


def restore_account(settings):
    """Load the saved session and restore it onto a fresh AppleAccount.

    Raises AppleAuthRequiredError (never a raw findmy exception) when no saved
    session exists, or when the saved session has expired.
    """
    path = _state_path(settings)
    if not path.exists():
        raise AppleAuthRequiredError("run 'findplus auth --provider apple-find-my'")
    data = json.loads(path.read_text(encoding="utf-8"))
    account = make_account(settings)
    try:
        account.restore_session(data)
    except Exception as exc:
        raise AppleAuthRequiredError(f"Apple session expired: {exc}") from exc
    return account


def sign_in_interactive(settings):
    """Prompt for Apple ID + password, handle 2FA, and save the resulting session.

    Boundary: a login() failure (bad credentials) is NOT wrapped — the raw
    findmy exception propagates so the caller sees the real cause. Only
    restore_session() failures (an expired saved session) are wrapped in
    AppleAuthRequiredError, since that path has no interactive user to show
    the raw error to.
    """
    account = make_account(settings)
    apple_id = click.prompt("Apple ID")
    password = click.prompt("Password", hide_input=True)
    account.login(apple_id, password)
    if account.requires_2fa():
        click.echo("2FA required. Select a method by number:")
        click.echo("  1) Trusted device")
        click.echo("  2) SMS")
        choice = click.prompt("Choice", type=click.Choice(["1", "2"]))
        methods = account.get_2fa_methods()
        if choice == "1":
            method = methods[0]
        else:
            method = next((m for m in methods if "sms" in type(m).__name__.lower()), methods[-1])
        method.request()
        code = click.prompt("2FA code")
        method.submit(code)
    save_account(account, settings)
    return account
