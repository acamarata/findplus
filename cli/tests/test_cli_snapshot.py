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


def test_help_contains_commands():
    result = CliRunner().invoke(main, ["--help"])
    expected = {
        "serve",
        "start",
        "stop",
        "status",
        "devices",
        "export",
        "prune",
        "auth",
        "poll-now",
        "install-service",
        "doctor",
    }
    for name in expected:
        assert name in result.output, f"missing command: {name}"
