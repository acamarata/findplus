"""Proves the committed cli/LICENSE copy stays in sync with the root LICENSE.

Purpose    : cli/pyproject.toml's `license-files = ["LICENSE"]` packages
             cli/LICENSE into the wheel's dist-info/licenses/ directory, and
             the sdist's `include` list picks up cli/LICENSE directly (it is
             inside the sdist build root). Both only work if cli/LICENSE is
             actually a copy of the repo's root LICENSE, not a stale fork.
Inputs     : repo root LICENSE, cli/LICENSE.
Outputs    : none (assertion only).
Constraints: read-only; no network, no fixtures, no real HOME.
"""

from __future__ import annotations

from pathlib import Path


def test_cli_license_matches_root_license():
    repo_root = Path(__file__).parents[2]
    root_license = repo_root / "LICENSE"
    cli_license = repo_root / "cli" / "LICENSE"

    assert root_license.is_file(), f"missing {root_license}"
    assert cli_license.is_file(), f"missing {cli_license}"
    assert cli_license.read_bytes() == root_license.read_bytes(), (
        "cli/LICENSE has drifted from the root LICENSE — re-copy it: cp LICENSE cli/LICENSE"
    )
