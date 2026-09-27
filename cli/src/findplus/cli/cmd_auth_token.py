"""`findplus auth --token`: Google sign-in with a token copied from your own Chrome.

Purpose    : CLI parity with the dashboard's main-Chrome flow. Opens Google's
             sign-in page in the user's Chrome, says where the `oauth_token`
             cookie is, then exchanges it through the same
             `token_signin.sign_in_with_oauth_token()` the API route calls.
Inputs     : The email and token from prompts (the token hidden), or the token
             from FINDPLUS_OAUTH_TOKEN for scripts. Nothing on argv, so the
             token never lands in shell history or `ps`.
Outputs    : secrets.json gains the session (0600); console lines only here.
Constraints: The token is never printed. Split out of cmd_auth.py to keep that
             file under the 300-line cap.
"""

from __future__ import annotations

import os
import sys

import click

TOKEN_ENV = "FINDPLUS_OAUTH_TOKEN"

_STEPS = (
    "1. Sign in to your Google account in that Chrome tab. The page may stay blank",
    "   or keep spinning after you sign in. That is expected.",
    "2. Open Chrome's developer tools (macOS: Option+Command+I; Windows and Linux:",
    "   Ctrl+Shift+I).",
    "3. Go to Application > Storage > Cookies > https://accounts.google.com.",
    "4. Click the oauth_token row and copy its Value. It starts with oauth2_4/.",
    "5. Paste it below with your Google email.",
)


def _explain(url: str) -> None:
    click.echo("")
    click.secho("Google sign-in with your own Chrome", bold=True)
    click.echo(f"Google's sign-in page: {url}")
    click.echo(
        "Google hands the Find Hub token only to a browser, as a cookie. Find+\n"
        "exchanges it right away and never stores it. It expires within minutes,\n"
        "so copy it right after you sign in.\n"
    )
    for line in _STEPS:
        click.echo(line)
    click.echo("")


def _open_page(url: str) -> None:
    """Offer to open the page; say so plainly when no browser could be opened."""
    from findplus.providers.google_findhub.open_signin import (
        BrowserOpenError,
        open_sign_in_page,
    )

    if not click.confirm("Open the page in Chrome now?", default=True):
        return
    try:
        browser = open_sign_in_page(url)
    except BrowserOpenError as exc:
        click.echo(str(exc))
        return
    click.echo("Opened in Google Chrome." if browser == "chrome" else "Opened in your browser.")


def auth_google_token(settings) -> None:
    """Prompt (or read the env) and sign in; exit 1 with a plain message on failure."""
    from findplus.providers.google_findhub.open_signin import EMBEDDED_SETUP_URL
    from findplus.providers.google_findhub.token_signin import (
        TokenSignInError,
        sign_in_with_oauth_token,
    )

    token = os.environ.get(TOKEN_ENV, "")
    _explain(EMBEDDED_SETUP_URL)
    if not token:
        _open_page(EMBEDDED_SETUP_URL)
    email = click.prompt("Google email")
    if not token:
        token = click.prompt("oauth_token value", hide_input=True)
    click.echo("Exchanging the token with Google...")
    try:
        account = sign_in_with_oauth_token(email, token)
    except TokenSignInError as exc:
        click.secho(str(exc), fg="red", err=True)
        sys.exit(1)
    click.secho(f"\nAuthenticated as {account}.", fg="green")
    click.echo(f"Credentials stored at {settings.secrets_file}")
    click.echo("Next: findplus devices")
