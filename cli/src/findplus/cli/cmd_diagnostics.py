"""Diagnostics and install commands: doctor, watchdog, theme, PIN reset.

Purpose    : Installation diagnostics, the watchdog health check, autostart/
             watchdog-job install, and small settings-adjacent utilities.
Inputs     : Mostly --yes confirmation skips; theme takes a required argument.
Outputs    : Console diagnostic tables; installed service/watchdog units.
Constraints: Split out of cmd_service.py (which was 398 lines, over the
             300-line/file hard rule) — same 12 findplus.cli commands as the
             pre-split cli.py, just distributed across two command modules
             instead of one. Zero behavior change from either grouping.
"""

from __future__ import annotations

import sys

import click

from findplus.config import VENDOR_GFMT, get_settings
from findplus.db.migrate import current_revision, head_revision
from findplus.db.session import session_scope
from findplus.logging_setup import configure_logging, get_logger

from ._fmt import _check, _prep, _row, _show_service_plan

log = get_logger("findplus.cli")


@click.command()
def doctor() -> None:
    """Diagnose the installation and report what is stored where."""
    _prep()
    from findplus import service
    from findplus.findhub.bootstrap import describe_stored_auth

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
        from findplus.findhub.bootstrap import ensure_gfmt_importable

        ensure_gfmt_importable()
        import NovaApi  # noqa: F401

        _check("GoogleFindMyTools importable", True, "")
    except Exception as exc:
        _check("GoogleFindMyTools importable", False, str(exc))
        ok = False

    click.secho("\nAuthentication material", bold=True)
    info = describe_stored_auth()
    _row("path", str(info["path"]))
    _row("exists", "yes" if info["exists"] else "no — run `findplus auth`")
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
    from findplus.state import get_tracked_devices

    with session_scope() as session:
        tracked = get_tracked_devices(session)
    _check(
        "device(s) tracked",
        bool(tracked),
        ", ".join(d.name for d in tracked) if tracked else "run `findplus devices --track-all`",
    )
    if tracked:
        rate = len(tracked) * 60 / settings.effective_poll_interval_minutes
        _row("request rate", f"~{rate:.0f} Google requests/hour")

    click.echo("")
    if ok and tracked and info["exists"]:
        click.secho("All checks passed.", fg="green")
    else:
        click.secho("Some checks need attention (see above).", fg="yellow")


@click.command()
def watchdog() -> None:
    """Check the local API and restart the service if it is not answering.

    Run periodically by the watchdog job. `KeepAlive` already covers a crashed
    process; this covers a process that is alive but wedged.
    """
    import urllib.error
    import urllib.request

    from findplus import service

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
        click.echo(f"findplus was not answering ({problem}); restart requested.")
    else:
        click.echo(f"findplus was not answering ({problem}), and no service is installed.")


@click.command("install-watchdog")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
def install_watchdog_cmd(yes: bool) -> None:
    """Show, then optionally install, the watchdog job."""
    _prep()
    from findplus import service

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


@click.command("reset-lock")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
def reset_lock(yes: bool) -> None:
    """Forgot your PIN? Remove the app lock from this machine.

    There is no cloud reset for the PIN, by design. Anyone who can run this
    command already has access to the database file, so this recovery path adds
    no exposure that did not already exist.
    """
    _prep()
    from findplus.appsettings import clear_pin, load_settings

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
    click.echo("Restart the service so running sessions pick this up: findplus start")


@click.command()
@click.argument("theme", type=click.Choice(["dark", "light", "system"]))
def theme(theme: str) -> None:
    """Set the dashboard theme without opening the UI."""
    _prep()
    from findplus.appsettings import save_theme

    with session_scope() as session:
        save_theme(session, theme)
    click.secho(f"Theme set to {theme}.", fg="green")


@click.command("install-service")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
def install_service(yes: bool) -> None:
    """Show, then optionally install, the autostart service."""
    _prep()
    from findplus import service

    p = service.plan()
    _show_service_plan(p)
    if not yes and not click.confirm("Install this now?", default=False):
        click.echo("Nothing was changed.")
        return
    service.install(confirmed=True)
    click.secho("Installed and started.", fg="green")
