"""The findplus click group: registers every command from cmd_* modules.

Purpose    : Single entry point for auth, device selection, polling, serving,
             exporting, diagnostics and autostart.
Inputs     : argv, dispatched by click to the matching subcommand.
Outputs    : Whatever the invoked subcommand prints; process exit code.
Constraints: This is the only file that calls click.group(); every command is
             defined elsewhere (cmd_service, cmd_diagnostics, cmd_devices,
             cmd_history) as a standalone @click.command() and registered
             here with main.add_command(), so command modules stay import-
             order-independent of the group itself.
"""

from __future__ import annotations

import click

from findplus import __version__

from . import cmd_apple, cmd_config, cmd_db, cmd_devices, cmd_diagnostics, cmd_history, cmd_service
from .doctor import doctor_cmd
from .providers import providers_cmd


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="findplus")
def main() -> None:
    """Local historical location timeline for a Google Find Hub tracker."""


main.add_command(cmd_service.auth)
main.add_command(cmd_service.serve)
main.add_command(cmd_service.start)
main.add_command(cmd_service.stop)
main.add_command(cmd_service.restart)
main.add_command(cmd_service.status)
main.add_command(cmd_service.uninstall)
main.add_command(cmd_service.open)
# install-service is kept as a named alias of `start` (same --yes/--program/
# --no-open options) per specs/cli-reference.md — no separate implementation.
main.add_command(cmd_service.start, name="install-service")

main.add_command(doctor_cmd)
main.add_command(cmd_diagnostics.watchdog)
main.add_command(cmd_diagnostics.install_watchdog_cmd)
main.add_command(cmd_diagnostics.reset_lock)
main.add_command(cmd_diagnostics.theme)

main.add_command(cmd_devices.devices)
main.add_command(cmd_devices.poll_now)

main.add_command(cmd_history.export)
main.add_command(cmd_history.prune)

main.add_command(cmd_config.config_cmd)
main.add_command(cmd_db.db_cmd)

main.add_command(providers_cmd, name="providers")

main.add_command(cmd_apple.apple_group, name="apple")


if __name__ == "__main__":
    main()
