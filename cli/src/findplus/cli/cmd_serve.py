"""The `serve` command: the daemon itself, plus its exclusivity and signal guards.

Purpose    : Run the local API/UI (and the poller unless disabled) in this
             process, refusing to start a second daemon and shutting down
             cleanly on SIGTERM/SIGINT.
Inputs     : --foreground, --no-poller, --host, --port.
Outputs    : The running server; daemon.json while it runs; exit 3 when a live
             daemon already answers, exit 1 when the server dies on its own.
Constraints: Split out of cmd_service.py to keep that module under the
             300-line/file hard rule. The create_app import stays
             function-local (matches the pre-split lazy import, avoiding a
             module-load-time dependency on the api/ package). No direct
             subprocess calls: platform work goes through the findplus.service
             facade (specs/service-package.md).
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import click
import httpx

from findplus import __version__
from findplus.config import PRIVATE_UMASK, get_settings, is_public_bind

from ._fmt import _prep


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


def _wait_for_stop(stop_event: threading.Event, server_thread: threading.Thread) -> int:
    """Block until a signal arrives or the server thread dies on its own.

    Polling the thread matters: if uvicorn cannot bind (a foreign process holds
    the port, so the daemon.json probe in `_check_exclusive` never saw it), the
    server thread exits immediately and a bare `stop_event.wait()` would hang
    forever while daemon.json advertises a daemon that is not serving anything.
    """
    while not stop_event.wait(0.25):
        if not server_thread.is_alive():
            return 1
    return 0


@click.command()
@click.option("--foreground", is_flag=True, help="Run in this terminal (used by the service).")
@click.option("--no-poller", is_flag=True, help="Serve the UI/API without polling Google.")
@click.option("--host", default=None)
@click.option("--port", default=None, type=int)
def serve(foreground: bool, no_poller: bool, host: str | None, port: int | None) -> None:
    """Start the local API/UI and (unless disabled) the polling service."""
    # Set again here, not only in the click group: the packaged daemon and the
    # LaunchAgent/systemd unit can invoke this command directly.
    os.umask(PRIVATE_UMASK)
    _prep(to_file=True)
    import uvicorn

    from findplus import service
    from findplus.api import create_app
    from findplus.poller import PollerService

    settings = get_settings()
    bind_host = host or settings.host
    bind_port = port or settings.port

    # I9 is enforced by Settings.host and by `config set HOST`; --host reached
    # uvicorn without passing either, so refuse here too, before daemon.json is
    # written or the server is constructed.
    if is_public_bind(bind_host):
        raise click.ClickException(
            f"Non-loopback host '{bind_host}' rejected. Set FINDPLUS_ALLOW_PUBLIC_BIND=1 to allow."
        )

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
    exit_code = 0
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

        exit_code = _wait_for_stop(stop_event, server_thread)
        if exit_code:
            click.secho(
                f"The API server stopped on its own. Port {bind_port} may already be in use.",
                fg="red",
            )
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

    if exit_code:
        sys.exit(exit_code)
