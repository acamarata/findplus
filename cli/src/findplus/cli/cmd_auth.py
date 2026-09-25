"""`findplus auth`: provider sign-in (Google via Chrome, Apple interactively).

Purpose    : The sign-in command and its two provider branches.
Inputs     : `--provider google-find-hub|apple-find-my`, plus `--status` and
             `--json` for a read-only report (specs/cli-reference.md § auth).
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

import json
import sys

import click

from findplus.config import get_settings

from ._fmt import _prep


def _print_auth_status(as_json: bool) -> None:
    """Report sign-in state for every provider, taking no sign-in side effect.

    Same object `GET /api/auth/status` serves, from the same call, so the CLI
    and the dashboard cannot drift (specs/auth-ui.md §5).
    """
    from findplus.providers.auth_status import build_auth_status

    status = build_auth_status()
    if as_json:
        click.echo(json.dumps(status))
        return
    click.echo(f"{'Provider':<20} {'Signed in':<12} Account")
    for provider in status["providers"]:
        signed = "yes" if provider["signed_in"] else "no"
        # "-", never str(None): a bare "None" in a terminal reads as a value.
        account = provider["account"] or "-"
        click.echo(f"{provider['id']:<20} {signed:<12} {account}")


def _google_preamble(settings) -> None:
    """What the terminal flow opens, kills and stores, said before it happens.

    The `pkill` line is about the CLI path only: it runs the vendor's original
    `create_driver`, which closes every Chrome window first. The dashboard path
    (providers/google_findhub/browser.py) uses its own profile and kills
    nothing, so it carries no such warning.
    """
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


@click.command()
@click.option("--status", "show_status", is_flag=True, help="Print sign-in status and exit.")
@click.option(
    "--json", "as_json", is_flag=True, help="With --status, print JSON instead of a table."
)
@click.option(
    "--provider",
    type=click.Choice(["google-find-hub", "apple-find-my"]),
    default="google-find-hub",
    help="Provider to authenticate: google-find-hub or apple-find-my",
)
def auth(provider: str, show_status: bool, as_json: bool) -> None:
    """Sign in to a provider (Google via Chrome, or Apple interactively)."""
    # _prep() first: build_auth_status() reads settings and the secrets store,
    # so the status path needs the same environment the sign-in path does.
    _prep()
    if show_status:
        _print_auth_status(as_json)
        return

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
        from findplus.providers.google_findhub.browser import MSG_CHROME_MISSING

        click.secho(MSG_CHROME_MISSING, fg="red", err=True)
        sys.exit(1)

    _google_preamble(settings)

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
    click.echo("  It contains the signed-in session tokens and your Apple ID. Your")
    click.echo("  Apple PASSWORD is sent to Apple for this sign-in only and is never")
    click.echo("  written to disk, so an expired session means signing in again.")
    click.echo("  Unless APPLE_ANISETTE_URL is set, the first sign-in downloads")
    click.echo("  anisette helper libraries (a few MB) from anisette.dl.mikealmel.ooo.\n")

    try:
        sign_in_interactive(settings)
    except Exception as exc:
        click.secho(f"\nAuthentication failed: {exc}", fg="red")
        sys.exit(1)

    click.secho("\nApple Find My authentication saved.", fg="green")
    click.echo("Next: findplus apple add-accessory")
