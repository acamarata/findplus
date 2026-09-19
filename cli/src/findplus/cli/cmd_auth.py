"""`findplus auth`: provider sign-in (Google via Chrome, Apple interactively).

Purpose    : The sign-in command and its two provider branches.
Inputs     : `--provider google-find-hub|apple-find-my` (specs/cli-reference.md § auth).
Outputs    : Credentials written by the provider itself (secrets.json /
             apple-account.json, both 0600); console guidance only here.
Constraints: Split out of cmd_service.py, which was over the 300-line/file hard
             rule once the Apple branch landed. `cmd_service.auth` re-exports
             this command, so main.py and every existing patch target are
             unchanged. Honesty rule (PRI hard rule 4): the Google preamble is
             shown only for the Google provider, and neither branch overstates
             what is stored.
"""

from __future__ import annotations

import sys

import click

from findplus.config import get_settings

from ._fmt import _prep


@click.command()
@click.option(
    "--provider",
    type=click.Choice(["google-find-hub", "apple-find-my"]),
    default="google-find-hub",
    help="Provider to authenticate: google-find-hub or apple-find-my",
)
def auth(provider: str) -> None:
    """Sign in to a provider (Google via Chrome, or Apple interactively)."""
    _prep()
    settings = get_settings()

    if provider == "apple-find-my":
        _auth_apple(settings)
        return

    from findplus.cli.doctor import check_chrome
    from findplus.providers.base import get_provider

    # Checked before anything is printed or confirmed: the upstream driver
    # needs a real Chrome, so without one the whole flow is a dead end and
    # saying so now beats failing halfway through a sign-in.
    if not check_chrome().passed:
        click.secho("Google Chrome was not found on this machine.", fg="red", err=True)
        click.echo(
            "Google sign-in drives Chrome directly and cannot run without it.\n"
            "Install it from https://www.google.com/chrome/ and run `findplus auth` again.",
            err=True,
        )
        sys.exit(1)

    click.echo("")
    click.secho("Google sign-in", bold=True)
    click.echo(
        "Chrome will open at Google's own account setup page. Sign in normally,\n"
        "including any 2-factor prompt. Nothing here bypasses Google's security.\n"
    )
    click.secho("Heads up: ", fg="yellow", nl=False)
    click.echo(
        "the upstream driver runs `pkill -f chrome` first, so any\n"
        "Chrome windows you currently have open will be closed. Save your work.\n"
    )
    click.echo("What gets stored, and where:")
    click.echo(f"  {settings.secrets_file}  (mode 0600, outside the git repository)")
    click.echo("  It contains: your Google account email, a long-lived Android (AAS)")
    click.echo("  token, a device-manager token, FCM push credentials, and the")
    click.echo("  end-to-end-encryption owner key needed to decrypt tag locations.")
    click.echo("  Your Google PASSWORD is never seen, stored, or transmitted by this app.\n")

    if not click.confirm("Open Chrome and sign in now?", default=True):
        raise click.Abort

    try:
        p = get_provider(provider)
        email = p.authenticate(interactive=True)
    except Exception as exc:
        click.secho(f"\nAuthentication failed: {exc}", fg="red")
        sys.exit(1)

    click.secho(f"\nAuthenticated as {email}.", fg="green")
    click.echo(f"Credentials stored at {settings.secrets_file}")
    click.echo("Next: findplus devices")


def _auth_apple(settings) -> None:
    """The apple-find-my branch of `auth`: availability guard, then interactive sign-in.

    Split out of `auth()` because the Google flow's Chrome-specific messaging
    does not apply here; `auth --provider apple-find-my` still shares the same
    command and the same --provider option (specs/cli-reference.md § auth).
    """
    from findplus.providers.apple_findmy import is_available

    avail, hint = is_available()
    if not avail:
        click.echo(f"Apple provider not installed. {hint}", err=True)
        sys.exit(1)

    from findplus.providers.apple_findmy.auth import sign_in_interactive

    click.echo("")
    click.secho("Apple Find My sign-in", bold=True)
    click.echo(
        "You will be prompted for your Apple ID and password, then a 2FA code\n"
        "(trusted device or SMS). Apple's own 2FA runs unmodified.\n"
    )
    click.echo("What gets stored, and where:")
    click.echo(f"  {settings.state_dir / 'apple-account.json'}  (mode 0600)")
    click.echo("  It contains an opaque, signed-in session token. Your Apple")
    click.echo("  PASSWORD is never seen, stored, or transmitted by this app beyond")
    click.echo("  the login call itself.\n")

    try:
        sign_in_interactive(settings)
    except Exception as exc:
        click.secho(f"\nAuthentication failed: {exc}", fg="red")
        sys.exit(1)

    click.secho("\nApple Find My authentication saved.", fg="green")
    click.echo("Next: findplus apple add-accessory")
