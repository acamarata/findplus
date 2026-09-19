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
@click.option("--track", "track_ids", multiple=True, help="Track this device id (repeatable).")
@click.option(
    "--track-all", "track_all_flag", is_flag=True, help="Track every device on the account."
)
@click.option("--untrack", "untrack_ids", multiple=True, help="Stop tracking a device id.")
@click.option("--default", "default_id", default=None, help="Device the dashboard opens on.")
@click.option("--refresh/--no-refresh", default=True, help="Re-query Find Hub for the list.")
def devices(
    track_ids: tuple[str, ...],
    track_all_flag: bool,
    untrack_ids: tuple[str, ...],
    default_id: str | None,
    refresh: bool,
) -> None:
    """List Find Hub devices and choose which ones to track.

    Any number of devices can be tracked at once. Tracking N devices costs N
    Google requests per poll cycle, so the effective request rate is shown.
    """
    _prep()
    from sqlalchemy import func
    from sqlalchemy import select as sa_select

    from bike_tracker.db.models import Device, LocationObservation
    from bike_tracker.findhub.client import FindHubClient
    from bike_tracker.ingest import upsert_device
    from bike_tracker.state import (
        get_tracked_devices,
        set_default_device,
        track_all,
        track_devices,
        untrack_devices,
    )

    mutating = bool(track_ids or track_all_flag or untrack_ids or default_id)

    # --track-all with an empty local table means the list was never fetched.
    # Refresh first rather than silently "tracking all 0 devices".
    if track_all_flag:
        from sqlalchemy import select as _sel

        with session_scope() as session:
            known = len(list(session.scalars(_sel(Device))))
        if known == 0:
            refresh = True
            mutating = False

    if refresh and not mutating:
        try:
            found = FindHubClient().list_devices()
        except Exception as exc:
            click.secho(f"Could not list devices: {exc}", fg="red")
            click.echo("If the session expired, run: bike-tracker auth")
            sys.exit(1)
        with session_scope() as session:
            for d in found:
                upsert_device(session, d.device_id, d.name)

    if track_all_flag:
        mutating = True

    if mutating:
        with session_scope() as session:
            try:
                if track_all_flag:
                    tracked = track_all(session)
                    click.secho(f"Now tracking all {len(tracked)} device(s).", fg="green")
                elif track_ids:
                    tracked = track_devices(session, track_ids, exclusive=True)
                    click.secho(
                        f"Now tracking {len(tracked)}: " + ", ".join(d.name for d in tracked),
                        fg="green",
                    )
                if untrack_ids:
                    removed = untrack_devices(session, untrack_ids)
                    click.secho(f"Stopped tracking {removed} device(s).", fg="yellow")
                    click.echo("Their history is kept; they are simply no longer polled.")
                if default_id:
                    set_default_device(session, default_id)
                    click.echo(f"Dashboard will open on {default_id}.")
            except LookupError as exc:
                click.secho(str(exc), fg="red")
                sys.exit(1)

    settings = get_settings()
    with session_scope() as session:
        rows = list(session.scalars(sa_select(Device).order_by(Device.name)))
        tracked = get_tracked_devices(session)
        if not rows:
            click.echo("No devices found on this account.")
            return

        click.echo("")
        click.secho(f"{'':4} {'NAME':<30} {'OBS':>7}  DEVICE ID", bold=True)
        for d in rows:
            count = session.scalar(
                sa_select(func.count(LocationObservation.id)).where(
                    LocationObservation.device_id == d.device_id
                )
            )
            mark = click.style(" [x]", fg="green") if d.is_tracked else " [ ]"
            click.echo(f"{mark} {d.name:<30} {count or 0:>7}  {d.device_id}")
        click.echo("")

        interval = settings.effective_poll_interval_minutes
        if tracked:
            rate = len(tracked) * 60 / interval
            click.echo(f"Tracking {len(tracked)} of {len(rows)} device(s).")
            click.echo(
                f"That is about {rate:.0f} Google requests/hour "
                f"({len(tracked)} device(s) every {interval:g} min), polled sequentially."
            )
        else:
            click.echo("Nothing is being tracked yet. Choose what to poll:")
            click.echo("  bike-tracker devices --track-all")
            click.echo("  bike-tracker devices --track <ID> --track <ID>")


# --------------------------------------------------------------------- poll
@main.command("poll-now")
def poll_now() -> None:
    """Run a single Find Hub poll immediately."""
    _prep()
    from bike_tracker.poller import poll_once

    cycle = poll_once()
    for o in cycle.outcomes:
        colour = {"ok": "green", "no_location": "yellow"}.get(o.status, "red")
        label = o.device_name or "(no device)"
        click.secho(f"{label:<28} {o.status}", fg=colour, nl=False)
        click.echo(f"   returned: {o.received}  new: {o.inserted}  dup: {o.duplicates}")
        if o.error_message:
            click.secho(f"    {o.error_message}", fg="red")
    click.echo("")
    click.echo(
        f"{len(cycle.outcomes)} device(s) polled  |  "
        f"{cycle.inserted} new observation(s)  |  {cycle.duplicates} duplicate(s)"
    )
    sys.exit(0 if cycle.ok else 1)


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
    from bike_tracker.state import get_tracked_devices
    from bike_tracker.timeline import day_bounds_utc, local_zone, observation_count_between

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
        click.secho("bike-tracker status", bold=True)
        _row("version", __version__)
        if tracked:
            _row("tracking", f"{len(tracked)} device(s)")
            for d in tracked:
                _row("", f"- {d.name}  ({d.device_id})")
            rate = len(tracked) * 60 / settings.effective_poll_interval_minutes
            _row("request rate", f"~{rate:.0f} Google requests/hour")
        else:
            _row("tracking", "nothing — run `bike-tracker devices --track-all`")
        _row("authenticated", "yes" if auth_info["exists"] else "no — run `bike-tracker auth`")
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


# ------------------------------------------------------------------ export
@main.command()
@click.option("--format", "fmt", type=click.Choice(["csv", "json", "gpx", "kml"]), default="csv")
@click.option("--day", default=None, help="Single local day, YYYY-MM-DD.")
@click.option("--start", default=None, help="Range start, YYYY-MM-DD.")
@click.option("--end", default=None, help="Range end, YYYY-MM-DD.")
@click.option("--all", "all_history", is_flag=True, help="Export the entire history.")
@click.option("--device-id", default=None, help="Limit to one device. Omit for all devices.")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None)
def export(
    fmt: str,
    day: str | None,
    start: str | None,
    end: str | None,
    all_history: bool,
    device_id: str | None,
    output: Path | None,
) -> None:
    """Export history to CSV, JSON, GPX or KML."""
    _prep()
    from bike_tracker.exporters import export as render
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
        rows = fetch_observations(session, device_id, start_utc, end_utc)
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

    click.secho("\nTracking", bold=True)
    from bike_tracker.state import get_tracked_devices

    with session_scope() as session:
        tracked = get_tracked_devices(session)
    _check(
        "device(s) tracked",
        bool(tracked),
        ", ".join(d.name for d in tracked) if tracked else "run `bike-tracker devices --track-all`",
    )
    if tracked:
        rate = len(tracked) * 60 / settings.effective_poll_interval_minutes
        _row("request rate", f"~{rate:.0f} Google requests/hour")

    click.echo("")
    if ok and tracked and info["exists"]:
        click.secho("All checks passed.", fg="green")
    else:
        click.secho("Some checks need attention (see above).", fg="yellow")


@main.command()
def watchdog() -> None:
    """Check the local API and restart the service if it is not answering.

    Run periodically by the watchdog job. `KeepAlive` already covers a crashed
    process; this covers a process that is alive but wedged.
    """
    import urllib.error
    import urllib.request

    from bike_tracker import service

    settings = get_settings()
    configure_logging(settings, to_file=True, console=False)
    url = f"http://{settings.host}:{settings.port}/api/health"

    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            if response.status == 200:
                log.info("watchdog_ok")
                return
            problem = f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        # 401 means the app lock is on and the API is healthy — not a failure.
        if exc.code == 401:
            log.info("watchdog_ok", note="locked but responding")
            return
        problem = f"HTTP {exc.code}"
    except Exception as exc:
        problem = str(exc)

    log.error("watchdog_restarting", url=url, problem=problem)
    if service.restart_service():
        click.echo(f"bike-tracker was not answering ({problem}); restart requested.")
    else:
        click.echo(f"bike-tracker was not answering ({problem}), and no service is installed.")


@main.command("install-watchdog")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
def install_watchdog_cmd(yes: bool) -> None:
    """Show, then optionally install, the watchdog job."""
    _prep()
    from bike_tracker import service

    p = service.watchdog_plan()
    _show_service_plan(p)
    click.echo(
        f"It runs every {service.WATCHDOG_INTERVAL_SECONDS // 60} minutes, asks the local\n"
        "API whether it is alive, and restarts the service only if it is not.\n"
    )
    if not yes and not click.confirm("Install this now?", default=False):
        click.echo("Nothing was changed.")
        return
    service.install_watchdog(confirmed=True)
    click.secho("Watchdog installed and started.", fg="green")


@main.command("reset-lock")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
def reset_lock(yes: bool) -> None:
    """Forgot your PIN? Remove the app lock from this machine.

    There is no cloud reset for the PIN, by design. Anyone who can run this
    command already has access to the database file, so this recovery path adds
    no exposure that did not already exist.
    """
    _prep()
    from bike_tracker.appsettings import clear_pin, load_settings

    with session_scope() as session:
        current = load_settings(session)
        if not current.pin_configured:
            click.echo("No PIN is set; nothing to reset.")
            return
        if not yes and not click.confirm(
            "Remove the app-lock PIN? The dashboard will open without one.", default=False
        ):
            raise click.Abort
        clear_pin(session)

    click.secho("App lock removed. Set a new PIN from Settings in the dashboard.", fg="green")
    click.echo("Restart the service so running sessions pick this up: bike-tracker start")


@main.command()
@click.argument("theme", type=click.Choice(["dark", "light", "system"]))
def theme(theme: str) -> None:
    """Set the dashboard theme without opening the UI."""
    _prep()
    from bike_tracker.appsettings import save_theme

    with session_scope() as session:
        save_theme(session, theme)
    click.secho(f"Theme set to {theme}.", fg="green")


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
