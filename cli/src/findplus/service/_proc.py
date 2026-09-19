"""Subprocess helper for the platform service managers.

Purpose    : Run a service-manager command without assuming its binary is
             installed. Containers, CI images and cross-platform test runs
             have no systemctl, launchctl or schtasks, and a status query
             there has to answer "not installed" instead of raising
             FileNotFoundError out of the CLI.
Inputs     : argv of the command to run; capture=True to read its output.
Outputs    : CompletedProcess. When the binary is missing the call is not
             attempted and a returncode of MISSING_BINARY_RC with empty
             stdout and stderr is returned. An empty argv is treated the
             same way, so a plan with no load command is a no-op.
Constraints: never raises FileNotFoundError, never uses check=True, never
             inspects the command beyond argv[0].
"""

from __future__ import annotations

import shutil
import subprocess

MISSING_BINARY_RC = 127


def run(argv: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    """Run `argv`, or report MISSING_BINARY_RC when argv[0] is not installed."""
    if not argv or shutil.which(argv[0]) is None:
        return subprocess.CompletedProcess(argv, MISSING_BINARY_RC, "", "")
    return subprocess.run(argv, capture_output=capture, text=True, check=False)
