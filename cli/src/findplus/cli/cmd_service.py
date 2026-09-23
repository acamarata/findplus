"""Service lifecycle commands: start/stop/restart/status/uninstall, open.

Purpose    : Control the installed daemon, report status, and open the dashboard.
Inputs     : Command-specific options (mostly --yes confirmation skips).
Outputs    : Console status tables; service files.
Constraints: Destructive/system-altering actions confirm before acting, unless
             --yes is passed. The daemon itself (`serve`) lives in cmd_serve.py,
             sign-in (`auth`) in cmd_auth.py and diagnostics (doctor, watchdog,
             install-watchdog, reset-lock, theme) in cmd_diagnostics.py — this
             file was over the 300-line/file hard rule with all four together.
             All three are re-exported below, so `cmd_service.auth` /
             `cmd_service.serve` still resolve for main.py and for tests.
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

from ._fmt import (
    _interactive,
    _prep,
    _print_device_table,
    _print_nothing_tracked_hint,
    _show_service_plan,
)

# Re-exported so `cmd_service.auth` / `cmd_service.serve` (main.py, tests) keep
# resolving after the splits.
from .cmd_auth import _auth_apple as _auth_apple
from .cmd_auth import auth as auth
from .cmd_serve import _check_exclusive as _check_exclusive
from .cmd_serve import _make_signal_handler as _make_signal_handler
from .cmd_serve import serve as serve


def _discover_and_track(google: bool, apple: bool, no_track_all: bool) -> None:
    """Branch B of `findplus start`: discover from every signed-in provider, show
    the table, and track everything unless --no-track-all.

    Split out of start() only to hold the 50-line function cap; the order of the
    steps is exactly service-and-settings.md § 1 B.1-B.4.
    """
    from findplus.db.session import session_scope
    from findplus.ingest import upsert_device
    from findplus.state import get_tracked_devices, track_all

    if google:
        from findplus.providers.google_findhub.client import FindHubClient

        try:
            found = FindHubClient().list_devices()
        except Exception as exc:
            click.secho(f"Could not list devices: {exc}", fg="red")
            sys.exit(1)
        with session_scope() as sess:
            for d in found:
                upsert_device(sess, d.device_id, d.name)
    if apple:
        from findplus.providers.apple_findmy.provider import AppleFindMyProvider

        try:
            apple_found = AppleFindMyProvider().list_devices()
        except Exception as exc:
            click.secho(f"Could not list devices: {exc}", fg="red")
            sys.exit(1)
        with session_scope() as sess:
            for d in apple_found:
                upsert_device(sess, d.device_id, d.name, provider="apple-find-my")

    with session_scope() as sess:
        _print_device_table(sess)
    if not no_track_all:
        with session_scope() as sess:
            now_tracked = track_all(sess)
            count = len(now_tracked)
        click.secho(f"Now tracking all {count} device(s).", fg="green")
    else:
        with session_scope() as sess:
            still_untracked = not get_tracked_devices(sess)
        if still_untracked:
            _print_nothing_tracked_hint()


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
@click.option("--no-track-all", is_flag=True, help="Discover devices but do not track them.")
def start(yes: bool, no_open: bool, program_override: str | None, no_track_all: bool) -> None:
    """Start the background service: auth check, then discover-and-track, then
    install/start — the whole fresh-account path in one run.

    Pinned in specs/service-and-settings.md § 1 (supersedes PROMPT.md D15).
    """
    _prep()
    from findplus import service
    from findplus.db.session import session_scope
    from findplus.providers.google_findhub.bootstrap import describe_stored_auth
    from findplus.state import get_tracked_devices

    from .cmd_poll import _POLL_NOW_UNAUTHENTICATED

    settings = get_settings()
    auth_info = describe_stored_auth()
    apple_signed_in = (settings.state_dir / "apple-account.json").exists()
    if not auth_info["exists"] and not apple_signed_in:
        click.echo("Find+ is not signed in yet. Run:")
        click.echo("  findplus auth       (or findplus setup for a guided walkthrough)")
        click.echo("  findplus start")
        sys.exit(_POLL_NOW_UNAUTHENTICATED)

    with session_scope() as sess:
        tracked = get_tracked_devices(sess)
    if not tracked:
        _discover_and_track(auth_info["exists"], apple_signed_in, no_track_all)

    program = _resolve_program(program_override)
    if not _install_or_start(service, program, yes):
        return

    click.echo(f"Dashboard: {settings.base_url}")
    if not no_open:
        webbrowser.open(settings.base_url)


def _resolve_program(program_override: str | None) -> str:
    if program_override:
        return str(Path(program_override).resolve())
    import shutil as _shutil

    found_bin = _shutil.which("findplus") or sys.argv[0]
    return str(Path(found_bin).resolve())


def _install_or_start(service, program: str, yes: bool) -> bool:
    """True once the service is running; False means the plan was only shown
    (no --yes), so the caller must stop before touching the dashboard."""
    if service.is_installed():
        service.start()
        click.echo("Service already installed; started.")
        return True
    _show_service_plan(service.plan(program=program))
    _show_service_plan(service.watchdog_plan(program=program))
    # R-P2-30.1 (UAT U1): an interactive terminal gets a real prompt instead
    # of a dead end; a script or pipe (install.sh, cron, CI) never blocks on
    # stdin and still needs --yes. Short-circuits on `not yes` first, so a
    # caller who already passed --yes never hits _interactive()/confirm() at all.
    prompt = "Install and start the service now?"
    if not yes and not (_interactive() and click.confirm(prompt, default=True)):
        click.echo("Pass --yes to write these files and load the service.")
        return False
    service.install(confirmed=True, program=program)
    service.install_watchdog(confirmed=True, program=program)
    click.secho("Service started.", fg="green")
    return True


@click.command()
def stop() -> None:
    """Stop the background service. Unit files are kept; the next login (or
    `findplus start`) brings it back. Use `findplus uninstall` to remove it."""
    _prep()
    from findplus import service

    # A clean-machine check found "Stopped." printed with no service ever
    # installed: say what actually happened instead.
    if not service.is_installed():
        click.echo("Find+ is not installed as a background service, so nothing was stopped.")
        click.echo("A daemon started with `findplus serve` stops with Ctrl+C.")
        return
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
