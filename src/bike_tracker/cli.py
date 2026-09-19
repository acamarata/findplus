"""Command line interface.

Purpose : One entry point for auth, device selection, polling, serving, exporting,
          diagnostics and autostart.
Constraints:
    - Destructive actions (history deletion, service install) require confirmation.
    - Nothing here prints or logs token material.
"""

from __future__ import annotations

import sys
import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import click

from bike_tracker import __version__
from bike_tracker.config import VENDOR_GFMT, get_settings
from bike_tracker.db.migrate import current_revision, head_revision, upgrade_to_head
from bike_tracker.db.session import session_scope
from bike_tracker.logging_setup import configure_logging, get_logger

log = get_logger("bike_tracker.cli")


def _prep(to_file: bool = False) -> None:
    settings = get_settings()
    configure_logging(settings, to_file=to_file)
    settings.ensure_dirs()
    upgrade_to_head()


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="bike-tracker")
def main() -> None:
    """Local historical location timeline for a Google Find Hub tracker."""


# --------------------------------------------------------------------- auth
@main.command()
def auth() -> None:
    """Sign in to Google with Chrome and store the session tokens."""
    _prep()
    settings = get_settings()
    from bike_tracker.findhub.client import FindHubClient

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
    click.echo("Next: bike-tracker devices")


# ------------------------------------------------------------------ devices
@main.command()
@click.option("--select", "select_id", default=None, help="Select this device id and exit.")
@click.option("--refresh/--no-refresh", default=True, help="Re-query Find Hub for the device list.")
def devices(select_id: str | None, refresh: bool) -> None:
    """List Find Hub devices and choose which one to track."""
    _prep()
    from bike_tracker.findhub.client import FindHubClient
    from bike_tracker.ingest import upsert_device
    from bike_tracker.state import get_selected_device, select_device

    if select_id:
        with session_scope() as session:
            try:
                device = select_device(session, select_id)
            except LookupError as exc:
                click.secho(str(exc), fg="red")
                sys.exit(1)
            click.secho(f"Now tracking: {device.name} ({device.device_id})", fg="green")
        return

    if refresh:
        try:
            found = FindHubClient().list_devices()
        except Exception as exc:
            click.secho(f"Could not list devices: {exc}", fg="red")
            click.echo("If the session expired, run: bike-tracker auth")
            sys.exit(1)
        with session_scope() as session:
            for d in found:
                upsert_device(session, d.device_id, d.name)

    from sqlalchemy import select as sa_select

    from bike_tracker.db.models import Device

    with session_scope() as session:
        rows = list(session.scalars(sa_select(Device).order_by(Device.name)))
        selected = get_selected_device(session)
        if not rows:
            click.echo("No devices found on this account.")
            return
        click.echo("")
        click.secho(f"{'':2} {'NAME':<34} DEVICE ID", bold=True)
        for d in rows:
            mark = "->" if selected and d.device_id == selected.device_id else "  "
            click.echo(f"{mark} {d.name:<34} {d.device_id}")
        click.echo("")
        if selected:
            click.echo(f"Currently tracking: {selected.name}")
        else:
            click.echo("Nothing selected yet. Choose your tag with:")
            click.echo("  bike-tracker devices --select <DEVICE ID>")


# --------------------------------------------------------------------- poll
@main.command("poll-now")
def poll_now() -> None:
    """Run a single Find Hub poll immediately."""
    _prep()
    from bike_tracker.poller import poll_once

    outcome = poll_once()
    colour = {"ok": "green", "no_location": "yellow"}.get(outcome.status, "red")
    click.secho(f"status: {outcome.status}", fg=colour)
    click.echo(
        f"returned: {outcome.received}  new: {outcome.inserted}  duplicate: {outcome.duplicates}"
    )
    if outcome.error_message:
        click.secho(outcome.error_message, fg="red")
    sys.exit(0 if outcome.ok else 1)


# -------------------------------------------------------------------- serve
@main.command()
@click.option("--foreground", is_flag=True, help="Run in this terminal (used by the service).")
@click.option("--no-poller", is_flag=True, help="Serve the UI/API without polling Google.")
@click.option("--host", default=None)
@click.option("--port", default=None, type=int)
def serve(foreground: bool, no_poller: bool, host: str | None, port: int | None) -> None:
    """Start the local API/UI and (unless disabled) the polling service."""
    _prep(to_file=True)
    import uvicorn

    from bike_tracker.api import create_app
    from bike_tracker.poller import PollerService

    settings = get_settings()
    bind_host = host or settings.host
    bind_port = port or settings.port

    poller: PollerService | None = None
    if not no_poller:
        poller = PollerService(settings)
        thread = threading.Thread(target=poller.run_forever, name="poller", daemon=True)
        thread.start()

    click.secho(f"bike-tracker {__version__}", bold=True)
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


@main.command()
def start() -> None:
    """Start the background service (installing it first if needed)."""
    _prep()
    from bike_tracker import service

    if not service.is_installed():
        click.echo("The background service is not installed yet.")
        _show_service_plan(service.plan())
        if not click.confirm("Install and start it now?", default=False):
            click.echo("Nothing was installed. Run `bike-tracker serve` to start in this terminal.")
            raise click.Abort
        service.install(confirmed=True)
    else:
        service.install(confirmed=True)  # rewrites + reloads the existing unit
    click.secho("Service started.", fg="green")
    click.echo(f"Dashboard: {get_settings().base_url}")


@main.command()
def stop() -> None:
    """Stop and remove the background service."""
    _prep()
    from bike_tracker import service

    if not service.is_installed():
        click.echo("No background service is installed.")
        return
    p = service.uninstall()
    click.secho(f"Stopped and removed {p.unit_path}", fg="green")


@main.command()
def status() -> None:
    """Show tracker, service and history status."""
    _prep()
    from sqlalchemy import desc, func
    from sqlalchemy import select as sa_select

    from bike_tracker import service
    from bike_tracker.db.models import LocationObservation, PollRun
    from bike_tracker.findhub.bootstrap import describe_stored_auth
    from bike_tracker.state import get_selected_device
    from bike_tracker.timeline import day_bounds_utc, local_zone, observation_count_between

    settings = get_settings()
    tz = local_zone()
    auth_info = describe_stored_auth()

    with session_scope() as session:
        device = get_selected_device(session)
        device_id = device.device_id if device else None
        total = session.scalar(sa_select(func.count(LocationObservation.id))) or 0
        latest = session.scalar(
            sa_select(LocationObservation).order_by(desc(LocationObservation.observed_at)).limit(1)
        )
        last_run = session.scalar(sa_select(PollRun).order_by(desc(PollRun.started_at)).limit(1))
        start_utc, end_utc = day_bounds_utc(datetime.now(tz).date(), tz)
        today = observation_count_between(session, device_id, start_utc, end_utc)

        click.echo("")
        click.secho("bike-tracker status", bold=True)
        _row("version", __version__)
        _row("tracker", f"{device.name} ({device.device_id})" if device else "none selected")
        _row("authenticated", "yes" if auth_info["exists"] else "no — run `bike-tracker auth`")
        _row("service installed", "yes" if service.is_installed() else "no")
        _row("service running", "yes" if service.is_running() else "no")
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


# ------------------------------------------------------------------ export
@main.command()
@click.option("--format", "fmt", type=click.Choice(["csv", "json", "gpx", "kml"]), default="csv")
@click.option("--day", default=None, help="Single local day, YYYY-MM-DD.")
@click.option("--start", default=None, help="Range start, YYYY-MM-DD.")
@click.option("--end", default=None, help="Range end, YYYY-MM-DD.")
@click.option("--all", "all_history", is_flag=True, help="Export the entire history.")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None)
def export(
    fmt: str,
    day: str | None,
    start: str | None,
    end: str | None,
    all_history: bool,
    output: Path | None,
) -> None:
    """Export history to CSV, JSON, GPX or KML."""
    _prep()
    from bike_tracker.exporters import export as render
    from bike_tracker.state import get_selected_device
    from bike_tracker.timeline import day_bounds_utc, fetch_observations, local_zone

    tz = local_zone()
    if all_history:
        start_utc = datetime(1970, 1, 1, tzinfo=UTC)
        end_utc = datetime.now(UTC) + timedelta(days=1)
        label = "all"
    elif day:
        target = date.fromisoformat(day)
        start_utc, end_utc = day_bounds_utc(target, tz)
        label = target.isoformat()
    elif start or end:
        s = date.fromisoformat(start) if start else date(1970, 1, 1)
        e = date.fromisoformat(end) if end else datetime.now(tz).date()
        start_utc, _ = day_bounds_utc(s, tz)
        _, end_utc = day_bounds_utc(e, tz)
        label = f"{s}_to_{e}"
    else:
        target = datetime.now(tz).date()
        start_utc, end_utc = day_bounds_utc(target, tz)
        label = target.isoformat()

    with session_scope() as session:
        device = get_selected_device(session)
        rows = fetch_observations(session, device.device_id if device else None, start_utc, end_utc)
        body = render(fmt, rows, tz, name=f"Bike history {label}")

    if output:
        output.write_text(body, encoding="utf-8")
        click.secho(f"Wrote {len(rows)} observation(s) to {output}", fg="green")
    else:
        click.echo(body)


# --------------------------------------------------------------- retention
@main.command("prune")
@click.option("--before", required=True, help="Delete observations before this local date.")
@click.option("--yes", is_flag=True, help="Actually delete. Without this it is a dry run.")
def prune(before: str, yes: bool) -> None:
    """Delete history before a date. Dry run unless --yes is given."""
    _prep()
    from sqlalchemy import func
    from sqlalchemy import select as sa_select

    from bike_tracker.db.models import LocationObservation
    from bike_tracker.timeline import day_bounds_utc, local_zone

    tz = local_zone()
    cutoff_utc, _ = day_bounds_utc(date.fromisoformat(before), tz)

    with session_scope() as session:
        count = (
            session.scalar(
                sa_select(func.count(LocationObservation.id)).where(
                    LocationObservation.observed_at < cutoff_utc
                )
            )
            or 0
        )
        if not yes:
            click.secho(f"Dry run: {count} observation(s) are older than {before}.", fg="yellow")
            click.echo("Re-run with --yes to delete them. History is never deleted silently.")
            return
        if not click.confirm(f"Permanently delete {count} observation(s) before {before}?"):
            raise click.Abort
        session.query(LocationObservation).filter(
            LocationObservation.observed_at < cutoff_utc
        ).delete(synchronize_session=False)
    click.secho(f"Deleted {count} observation(s).", fg="green")


# ------------------------------------------------------------------- misc
@main.command()
def open() -> None:
    """Open the dashboard in the default browser."""
    import webbrowser

    url = get_settings().base_url
    click.echo(f"Opening {url}")
    webbrowser.open(url)


@main.command()
def doctor() -> None:
    """Diagnose the installation and report what is stored where."""
    _prep()
    from bike_tracker import service
    from bike_tracker.findhub.bootstrap import describe_stored_auth

    settings = get_settings()
    ok = True

    click.echo("")
    click.secho("Environment", bold=True)
    _row("python", sys.version.split()[0])
    _row("platform", f"{sys.platform}")
    _row("service manager", service.detect_manager())

    click.secho("\nUpstream integration", bold=True)
    vendored = (VENDOR_GFMT / "NovaApi").is_dir()
    _check("GoogleFindMyTools vendored", vendored, str(VENDOR_GFMT))
    ok &= vendored
    try:
        from bike_tracker.findhub.bootstrap import ensure_gfmt_importable

        ensure_gfmt_importable()
        import NovaApi  # noqa: F401

        _check("GoogleFindMyTools importable", True, "")
    except Exception as exc:
        _check("GoogleFindMyTools importable", False, str(exc))
        ok = False

    click.secho("\nAuthentication material", bold=True)
    info = describe_stored_auth()
    _row("path", str(info["path"]))
    _row("exists", "yes" if info["exists"] else "no — run `bike-tracker auth`")
    if info["exists"]:
        _row("permissions", str(info["permissions"]))
        _row("stored keys", ", ".join(info["keys_present"]) or "(none)")
        if info["permissions"] != "0o600":
            click.secho("  warning: expected mode 0600", fg="yellow")
    click.echo("  Values are never printed. Your Google password is never stored.")

    click.secho("\nStorage", bold=True)
    _row("database", str(settings.database_path))
    _row("schema", f"{current_revision()} (head {head_revision()})")
    _row("state dir", str(settings.state_dir))
    _row("log file", str(settings.log_file))

    click.secho("\nNetwork posture", bold=True)
    _row("bind address", f"{settings.host}:{settings.port}")
    _check("local-only bind", settings.host in {"127.0.0.1", "localhost", "::1"}, settings.host)

    click.secho("\nSelection", bold=True)
    from bike_tracker.state import get_selected_device

    with session_scope() as session:
        device = get_selected_device(session)
    _check(
        "tracker selected",
        device is not None,
        f"{device.name} ({device.device_id})" if device else "run `bike-tracker devices`",
    )

    click.echo("")
    if ok and device is not None and info["exists"]:
        click.secho("All checks passed.", fg="green")
    else:
        click.secho("Some checks need attention (see above).", fg="yellow")


@main.command("install-service")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
def install_service(yes: bool) -> None:
    """Show, then optionally install, the autostart service."""
    _prep()
    from bike_tracker import service

    p = service.plan()
    _show_service_plan(p)
    if not yes and not click.confirm("Install this now?", default=False):
        click.echo("Nothing was changed.")
        return
    service.install(confirmed=True)
    click.secho("Installed and started.", fg="green")


def _show_service_plan(p) -> None:
    click.echo("")
    click.secho("This is exactly what will be installed:", bold=True)
    _row("platform", p.platform)
    _row("manager", p.manager)
    _row("file", str(p.unit_path))
    _row("load", " ".join(p.load_command))
    click.echo("\n--- file contents ---")
    click.echo(p.unit_text.strip())
    click.echo("--- end ---")
    click.echo("\nUser-level only. No sudo, nothing written outside your home directory.\n")


def _row(label: str, value: str) -> None:
    click.echo(f"  {label:<20} {value}")


def _check(label: str, ok: bool, detail: str) -> None:
    mark = click.style("ok  ", fg="green") if ok else click.style("FAIL", fg="red")
    click.echo(f"  [{mark}] {label:<32} {detail}")


if __name__ == "__main__":
    main()
