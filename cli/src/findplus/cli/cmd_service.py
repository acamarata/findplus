"""Service lifecycle commands: auth, start/stop/restart/status/uninstall, open.

Purpose    : Sign-in, control the installed daemon, report status, and open the
             dashboard.
Inputs     : Command-specific options (mostly --yes confirmation skips).
Outputs    : Console status tables; service files.
Constraints: Destructive/system-altering actions confirm before acting, unless
             --yes is passed. The daemon itself (`serve`) lives in cmd_serve.py
             and diagnostics (doctor, watchdog, install-watchdog, reset-lock,
             theme) in cmd_diagnostics.py — this file was over the
             300-line/file hard rule with all three together.
             This module contains zero direct subprocess calls: everything
             platform-specific goes through the findplus.service facade
             (specs/service-package.md — no ServiceManager classes here).
"""

from __future__ import annotations

import json
import sys
import webbrowser
from pathlib import Path

import click
import httpx

from findplus.config import get_settings

from ._fmt import _prep, _show_service_plan

# Re-exported so `cmd_service.serve` (main.py, tests) keeps resolving after the split.
from .cmd_serve import _check_exclusive as _check_exclusive
from .cmd_serve import _make_signal_handler as _make_signal_handler
from .cmd_serve import serve as serve


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


@click.command()
@click.option("--yes", is_flag=True, help="Write and load the service files without asking.")
@click.option("--no-open", is_flag=True, help="Do not open the dashboard in a browser.")
@click.option(
    "--program",
    "-P",
    "program_override",
    default=None,
    metavar="PATH",
    help="Path to the daemon executable. The desktop app passes "
    "/Applications/Find+.app/Contents/MacOS/findplus-daemon here.",
)
def start(yes: bool, no_open: bool, program_override: str | None) -> None:
    """Start the background service (D15): auth check, then tracked-devices
    check, then install/start — installing it first if needed."""
    _prep()
    from findplus import service
    from findplus.db.session import session_scope
    from findplus.ingest import upsert_device
    from findplus.providers.google_findhub.bootstrap import describe_stored_auth
    from findplus.state import get_tracked_devices

    settings = get_settings()
    auth_info = describe_stored_auth()
    if not auth_info["exists"]:
        click.echo("Find+ is not authenticated yet. Run these two commands:")
        click.echo("  findplus auth")
        click.echo("  findplus start")
        sys.exit(0)

    with session_scope() as sess:
        tracked = get_tracked_devices(sess)
    if not tracked:
        from findplus.providers.google_findhub.client import FindHubClient

        try:
            found = FindHubClient().list_devices()
        except Exception as exc:
            click.secho(f"Could not list devices: {exc}", fg="red")
            sys.exit(1)
        with session_scope() as sess:
            for d in found:
                upsert_device(sess, d.device_id, d.name)
        webbrowser.open(f"{settings.base_url}/#devices")
        click.echo(
            f"No devices are tracked yet. Pick the ones to track at {settings.base_url}/#devices"
        )
        click.echo("Then run `findplus start` again to install the background service.")
        sys.exit(0)

    program = None
    if program_override:
        program = str(Path(program_override).resolve())
    else:
        import shutil as _shutil

        found_bin = _shutil.which("findplus") or sys.argv[0]
        program = str(Path(found_bin).resolve())

    if service.is_installed():
        service.start()
        click.echo("Service already installed; started.")
    else:
        _show_service_plan(service.plan(program=program))
        _show_service_plan(service.watchdog_plan(program=program))
        if not yes:
            click.echo("Pass --yes to write these files and load the service.")
            return
        service.install(confirmed=True, program=program)
        service.install_watchdog(confirmed=True, program=program)
        click.secho("Service started.", fg="green")

    click.echo(f"Dashboard: {settings.base_url}")
    if not no_open:
        webbrowser.open(settings.base_url)


@click.command()
def stop() -> None:
    """Stop the background service. Unit files are kept; the next login (or
    `findplus start`) brings it back. Use `findplus uninstall` to remove it."""
    _prep()
    from findplus import service

    service.stop()
    click.echo("Stopped. The unit files are kept and the service returns at the next login.")
    click.echo("Run `findplus uninstall --yes` to remove the unit files and daemon.json.")


@click.command()
def restart() -> None:
    """Restart the background service."""
    _prep()
    from findplus import service

    service.restart()
    click.echo("Restarted.")


@click.command()
@click.option("--json", "json_flag", is_flag=True, help="Print machine-readable JSON.")
def status(json_flag: bool) -> None:
    """Show service, watchdog and daemon status."""
    _prep()
    from findplus import service

    settings = get_settings()
    sd = service.status()

    op: dict = {}
    try:
        r = httpx.get(f"{settings.base_url}/api/status", timeout=2.0)
        if r.status_code == 200:
            op = r.json()
        elif r.status_code == 401:
            op = {"lock_state": "locked"}
    except Exception:
        pass

    out = {
        "installed": sd.installed,
        "loaded": sd.loaded,
        "running": sd.running,
        "watchdog_installed": sd.watchdog_installed,
        "watchdog_loaded": sd.watchdog_loaded,
        "pid": sd.pid,
        "port": op.get("port", sd.port),
        # Same daemon.json fallback as `port`: with the daemon unreachable the
        # live /api/status call gives nothing, but daemon.json still records the
        # version the running process was started with.
        "version": op.get("version", sd.version),
        "last_poll_at": op.get("last_poll_at"),
        "lock_state": op.get("lock_state", "unknown"),
        "providers": op.get("providers", []),
        "alerts_configured": op.get("alerts_configured", False),
    }

    if json_flag:
        click.echo(json.dumps(out))
        return

    click.echo(
        f"service   installed={sd.installed} loaded={sd.loaded} "
        f"running={sd.running} pid={sd.pid if sd.pid is not None else '-'}"
    )
    click.echo(f"watchdog  installed={sd.watchdog_installed} loaded={sd.watchdog_loaded}")
    click.echo(f"port      {out['port']}")
    click.echo(f"version   {out['version']}")
    click.echo(f"lock      {out['lock_state']}")


@click.command()
@click.option("--yes", is_flag=True, help="Unload and delete the unit files without asking.")
def uninstall(yes: bool) -> None:
    """Unload and delete the service and watchdog unit files, and daemon.json."""
    _prep()
    from findplus import service

    if not yes:
        click.echo("Pass --yes to unload and delete the unit files and remove daemon.json.")
        return

    service.uninstall()
    service.uninstall_watchdog()
    (get_settings().state_dir / "daemon.json").unlink(missing_ok=True)
    click.echo("Uninstalled. Run `findplus start --yes` to reinstall.")


@click.command()
def open() -> None:
    """Open the dashboard in the default browser."""
    url = get_settings().base_url
    click.echo(f"Opening {url}")
    webbrowser.open(url)
