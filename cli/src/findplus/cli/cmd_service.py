"""Service lifecycle commands: auth, serve, start/stop, status, open.

Purpose    : Sign-in, run the daemon (foreground or as an installed service),
             report status, and open the dashboard.
Inputs     : Command-specific options (mostly --yes confirmation skips).
Outputs    : Console status tables; the running server (serve); service files.
Constraints: Destructive/system-altering actions confirm before acting, unless
             --yes is passed. The 'serve' command's create_app import stays
             function-local (matches the pre-split lazy import, avoiding a
             module-load-time dependency on the api/ package).
             Diagnostics/install-adjacent commands (doctor, watchdog,
             install-watchdog, reset-lock, theme, install-service) live in
             cmd_diagnostics.py — this file alone was 398 lines, over the
             300-line/file hard rule, so it was split in two.
"""

from __future__ import annotations

import sys
import threading
from datetime import UTC, datetime

import click

from findplus import __version__
from findplus.config import get_settings
from findplus.db.migrate import current_revision
from findplus.db.session import session_scope

from ._fmt import _prep, _row, _show_service_plan


@click.command()
def auth() -> None:
    """Sign in to Google with Chrome and store the session tokens."""
    _prep()
    settings = get_settings()
    from findplus.findhub.client import FindHubClient

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
        email = FindHubClient(settings).authenticate()
    except Exception as exc:
        click.secho(f"\nAuthentication failed: {exc}", fg="red")
        sys.exit(1)

    click.secho(f"\nAuthenticated as {email}.", fg="green")
    click.echo(f"Credentials stored at {settings.secrets_file}")
    click.echo("Next: findplus devices")


@click.command()
@click.option("--foreground", is_flag=True, help="Run in this terminal (used by the service).")
@click.option("--no-poller", is_flag=True, help="Serve the UI/API without polling Google.")
@click.option("--host", default=None)
@click.option("--port", default=None, type=int)
def serve(foreground: bool, no_poller: bool, host: str | None, port: int | None) -> None:
    """Start the local API/UI and (unless disabled) the polling service."""
    _prep(to_file=True)
    import uvicorn

    from findplus.api import create_app
    from findplus.poller import PollerService

    settings = get_settings()
    bind_host = host or settings.host
    bind_port = port or settings.port

    poller: PollerService | None = None
    if not no_poller:
        poller = PollerService(settings)
        thread = threading.Thread(target=poller.run_forever, name="poller", daemon=True)
        thread.start()

    click.secho(f"findplus {__version__}", bold=True)
    click.echo(f"Dashboard : http://{bind_host}:{bind_port}")
    click.echo(f"Database  : {settings.database_path}")
    click.echo(f"Logs      : {settings.log_file}")
    cadence = "disabled" if no_poller else f"every {settings.effective_poll_interval_minutes:g} min"
    click.echo(f"Polling   : {cadence}")
    try:
        uvicorn.run(
            create_app(),
            host=bind_host,
            port=bind_port,
            log_level=settings.log_level.lower(),
            access_log=False,
        )
    finally:
        if poller:
            poller.stop()


@click.command()
def start() -> None:
    """Start the background service (installing it first if needed)."""
    _prep()
    from findplus import service

    if not service.is_installed():
        click.echo("The background service is not installed yet.")
        _show_service_plan(service.plan())
        if not click.confirm("Install and start it now?", default=False):
            click.echo("Nothing was installed. Run `findplus serve` to start in this terminal.")
            raise click.Abort
        service.install(confirmed=True)
    else:
        service.install(confirmed=True)  # rewrites + reloads the existing unit
    click.secho("Service started.", fg="green")
    click.echo(f"Dashboard: {get_settings().base_url}")


@click.command()
def stop() -> None:
    """Stop and remove the background service."""
    _prep()
    from findplus import service

    if not service.is_installed():
        click.echo("No background service is installed.")
        return
    p = service.uninstall()
    click.secho(f"Stopped and removed {p.unit_path}", fg="green")


@click.command()
def status() -> None:
    """Show tracker, service and history status."""
    _prep()
    from sqlalchemy import desc, func
    from sqlalchemy import select as sa_select

    from findplus import service
    from findplus.db.models import LocationObservation, PollRun
    from findplus.findhub.bootstrap import describe_stored_auth
    from findplus.state import get_tracked_devices
    from findplus.timeline import day_bounds_utc, local_zone, observation_count_between

    settings = get_settings()
    tz = local_zone()
    auth_info = describe_stored_auth()

    with session_scope() as session:
        tracked = get_tracked_devices(session)
        device_id = None
        total = session.scalar(sa_select(func.count(LocationObservation.id))) or 0
        latest = session.scalar(
            sa_select(LocationObservation).order_by(desc(LocationObservation.observed_at)).limit(1)
        )
        last_run = session.scalar(sa_select(PollRun).order_by(desc(PollRun.started_at)).limit(1))
        start_utc, end_utc = day_bounds_utc(datetime.now(tz).date(), tz)
        today = observation_count_between(session, device_id, start_utc, end_utc)

        click.echo("")
        click.secho("findplus status", bold=True)
        _row("version", __version__)
        if tracked:
            _row("tracking", f"{len(tracked)} device(s)")
            for d in tracked:
                _row("", f"- {d.name}  ({d.device_id})")
            rate = len(tracked) * 60 / settings.effective_poll_interval_minutes
            _row("request rate", f"~{rate:.0f} Google requests/hour")
        else:
            _row("tracking", "nothing — run `findplus devices --track-all`")
        _row("authenticated", "yes" if auth_info["exists"] else "no — run `findplus auth`")
        _row("service installed", "yes" if service.is_installed() else "no")
        _row("service running", "yes" if service.is_running() else "no")
        _row("watchdog installed", "yes" if service.watchdog_installed() else "no")
        _row("poll interval", f"{settings.effective_poll_interval_minutes:g} min")
        _row("database", f"{settings.database_path} (schema {current_revision()})")
        _row("observations", f"{total} total, {today} today")
        if latest:
            age = (datetime.now(UTC) - latest.observed_at).total_seconds()
            seen = f"{latest.observed_at.astimezone(tz):%Y-%m-%d %H:%M:%S %Z}"
            got = f"{latest.first_fetched_at.astimezone(tz):%Y-%m-%d %H:%M:%S %Z}"
            _row("last observed", f"{seen} ({age / 60:.0f} min ago)")
            _row("last retrieved", got)
        if last_run:
            ran = f"{last_run.started_at.astimezone(tz):%Y-%m-%d %H:%M:%S %Z}"
            _row("last poll", f"{ran} -> {last_run.status}")
            if last_run.error_message:
                _row("last error", last_run.error_message[:120])
        click.echo("")


@click.command()
def open() -> None:
    """Open the dashboard in the default browser."""
    import webbrowser

    url = get_settings().base_url
    click.echo(f"Opening {url}")
    webbrowser.open(url)
