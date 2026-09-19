"""Command-inventory regression guard for the cli/ package split.

Purpose    : Catch a command silently dropped or renamed when the cli/
             package grows in later epics.
Inputs     : `main` invoked with --help via click's CliRunner.
Outputs    : Assertions on exit code and command-name presence.
Constraints: Zero behavior change from the pre-split monolith is the bar.
"""

from __future__ import annotations

from click.testing import CliRunner

from findplus.cli.main import main


def test_help_exits_zero():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0, result.output


#: Every command the pre-split cli.py registered on the group, by its click name.
#: The pre-split module had 16; a split that quietly loses one must fail here.
EXPECTED_COMMANDS = {
    "apple",
    "auth",
    "config",
    "db",
    "devices",
    "doctor",
    "export",
    "groups",
    "install-service",
    "install-watchdog",
    "open",
    "places",
    "poll-now",
    "providers",
    "prune",
    "reset-lock",
    "restart",
    "serve",
    "start",
    "status",
    "stop",
    "theme",
    "uninstall",
    "version",
    "watchdog",
}


def test_help_contains_commands():
    result = CliRunner().invoke(main, ["--help"])
    for name in EXPECTED_COMMANDS:
        assert name in result.output, f"missing command: {name}"


def test_registered_command_set_is_exact():
    """Names AND count, so a rename or an accidental extra also fails.

    `--help` output alone cannot catch a command that was renamed to something
    whose old name still appears elsewhere in the help text, nor an extra
    command added without a spec change. Read the group's registry instead.
    """
    assert set(main.commands) == EXPECTED_COMMANDS
