"""Proves the Homebrew caveats send new installs to the guided wizard.

Purpose    : Every install channel gives the same first instruction. install.sh
             ends with `findplus setup`, so the brew formula's caveats block has
             to as well (specs/service-and-settings.md § 3). gen-formula.sh
             copies the template verbatim apart from the url/sha256/resources
             tokens, so the template is the only place this text lives.
Inputs     : packaging/homebrew/findplus.rb.tmpl.
Outputs    : none (assertions only).
Constraints: read-only; no network, no fixtures, no real HOME.
"""

from __future__ import annotations

from pathlib import Path


def test_caveats_point_at_setup_not_auth():
    repo_root = Path(__file__).parents[2]
    tmpl = repo_root / "packaging" / "homebrew" / "findplus.rb.tmpl"

    assert tmpl.is_file(), f"missing {tmpl}"
    text = tmpl.read_text()

    assert "`findplus setup` to begin." in text
    assert "`findplus auth` to begin." not in text
