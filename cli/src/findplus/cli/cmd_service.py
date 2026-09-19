"""Service lifecycle commands: auth, serve, start/stop/restart/status/uninstall, open.

Purpose    : Sign-in, run the daemon (foreground or as an installed service),
             report status, and open the dashboard.
Inputs     : Command-specific options (mostly --yes confirmation skips).
Outputs    : Console status tables; the running server (serve); service files.
Constraints: Destructive/system-altering actions confirm before acting, unless
             --yes is passed. The 'serve' command's create_app import stays
             function-local (matches the pre-split lazy import, avoiding a
             module-load-time dependency on the api/ package).
             Diagnostics/install-adjacent commands (doctor, watchdog,
             install-watchdog, reset-lock, theme) live in cmd_diagnostics.py —
             this file alone was 398 lines, over the 300-line/file hard rule,
             so it was split in two.
             This module contains zero direct subprocess calls: everything
             platform-specific goes through the findplus.service facade
             (specs/service-package.md — no ServiceManager classes here).
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path

import click
import httpx

from findplus import __version__
from findplus.config import get_settings

from ._fmt import _prep, _show_service_plan


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


def _check_exclusive(state_dir: Path) -> tuple[bool, str]:
    """Whether a live findplus daemon already answers on the port in daemon.json.

    A 200 with app=='findplus' OR a 401 (locked, but still a running daemon)
    both count as "already running". A stale daemon.json (dead pid, refused
    connection, or a foreign service on that port) is ignored: serve proceeds
    normally and will overwrite it.
    """
    daemon_json = state_dir / "daemon.json"
    if not daemon_json.exists():
        return (False, "")
    try:
        data = json.loads(daemon_json.read_text())
        port = int(data["port"])
        host = str(data.get("host", "127.0.0.1"))
        url = f"http://{host}:{port}"
        r = httpx.get(f"{url}/api/health", timeout=2.0)
        if r.status_code == 401:
            return (True, f"{url}/")
        if r.status_code == 200 and r.json().get("app") == "findplus":
            return (True, f"{url}/")
    except Exception:
        pass  # stale daemon.json or unreachable daemon
    return (False, "")


def _make_signal_handler(stop_event: threading.Event) -> Callable[[int, object], None]:
    """A pure factory: no module-level mutable state, so this is unit-testable
    without touching a global. `serve()` owns the one `stop_event` it builds."""

    def _handle_signal(sig: int, frame: object) -> None:
        stop_event.set()

    return _handle_signal


@click.command()
@click.option("--foreground", is_flag=True, help="Run in this terminal (used by the service).")
@click.option("--no-poller", is_flag=True, help="Serve the UI/API without polling Google.")
@click.option("--host", default=None)
@click.option("--port", default=None, type=int)
def serve(foreground: bool, no_poller: bool, host: str | None, port: int | None) -> None:
    """Start the local API/UI and (unless disabled) the polling service."""
    _prep(to_file=True)
    import uvicorn

    from findplus import service
    from findplus.api import create_app
    from findplus.poller import PollerService

    settings = get_settings()
    bind_host = host or settings.host
    bind_port = port or settings.port

    already_running, url = _check_exclusive(settings.state_dir)
    if already_running:
        click.echo(f"Find+ is already running at {url}")
        sys.exit(3)

    stop_event = threading.Event()
    signal.signal(signal.SIGINT, _make_signal_handler(stop_event))
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, _make_signal_handler(stop_event))

    click.secho(f"findplus {__version__}", bold=True)
    click.echo(f"Dashboard : http://{bind_host}:{bind_port}")
    click.echo(f"Database  : {settings.database_path}")
    click.echo(f"Logs      : {settings.log_file}")
    cadence = "disabled" if no_poller else f"every {settings.effective_poll_interval_minutes:g} min"
    click.echo(f"Polling   : {cadence}")

    poller: PollerService | None = None
    poller_thread: threading.Thread | None = None
    server: uvicorn.Server | None = None
    server_thread: threading.Thread | None = None
    try:
        service.write_daemon_file(
            pid=os.getpid(), port=bind_port, host=bind_host, version=__version__, argv=sys.argv
        )

        if not no_poller:
            poller = PollerService(settings)
            poller_thread = threading.Thread(target=poller.run_forever, name="poller", daemon=True)
            poller_thread.start()

        config = uvicorn.Config(
            create_app(),
            host=bind_host,
            port=bind_port,
            log_level=settings.log_level.lower(),
            access_log=False,
        )
        server = uvicorn.Server(config)
        server.install_signal_handlers = False
        server_thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
        server_thread.start()

        stop_event.wait()
    finally:
        if server is not None:
            server.should_exit = True
        if server_thread is not None:
            server_thread.join(timeout=5.0)
        if poller is not None:
            poller.stop()
        if poller_thread is not None:
            poller_thread.join(timeout=5.0)
        (settings.state_dir / "daemon.json").unlink(missing_ok=True)


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
    from findplus.findhub.bootstrap import describe_stored_auth
    from findplus.ingest import upsert_device
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
        from findplus.findhub.client import FindHubClient

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
        "version": op.get("version"),
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
