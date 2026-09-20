"""The findplus.findhub compatibility shim still announces its own deprecation.

Purpose    : cli/pyproject.toml carried a blanket `ignore::DeprecationWarning`
             (CF-3), which silenced our own deprecations alongside third-party
             noise. The allowlist that replaced it deliberately does NOT cover
             `findplus.findhub`, so this test fails the moment the shim's warning
             is suppressed again or quietly dropped.
Inputs     : A fresh import of findplus.findhub.
Outputs    : One pytest.warns assertion.
Constraints: The shim warns at import time and import is cached, so the module
             and the legacy submodule aliases it registers must be evicted from
             sys.modules first or the warning never fires a second time.
"""

from __future__ import annotations

import importlib
import sys

import pytest

_SHIM_MODULES = (
    "findplus.findhub",
    "findplus.findhub.client",
    "findplus.findhub.types",
    "findplus.findhub.bootstrap",
)


def test_findhub_shim_still_warns() -> None:
    for name in _SHIM_MODULES:
        sys.modules.pop(name, None)

    with pytest.warns(DeprecationWarning, match="findplus.findhub is deprecated"):
        importlib.import_module("findplus.findhub")


def test_the_shim_still_re_exports_the_client() -> None:
    """The warning is not the point on its own: the legacy path must still work."""
    module = importlib.import_module("findplus.findhub")

    assert module.FindHubClient is not None


def test_the_blanket_deprecation_ignore_stays_out_of_pyproject() -> None:
    """CF-3 itself: the ini filter, not the shim, is what was wrong.

    `pytest.warns` installs its own `simplefilter("always")`, so the two tests
    above pass even with a blanket `ignore::DeprecationWarning` restored —
    they prove the shim warns, never that the suite would hear it. This reads
    the setting they cannot see (CR-C-E1 F6).
    """
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    filters = tomllib.loads(pyproject.read_text())["tool"]["pytest"]["ini_options"][
        "filterwarnings"
    ]

    assert "default::DeprecationWarning" in filters, "our own deprecations must surface"
    blanket = [f for f in filters if f.strip() in {"ignore::DeprecationWarning", "ignore"}]
    assert blanket == [], f"a blanket ignore is back and hides our deprecations: {blanket}"
    # Third-party noise may still be silenced, but only module by module.
    for entry in filters:
        if entry.startswith("ignore"):
            assert ":" in entry.removeprefix("ignore::"), f"unscoped ignore: {entry}"
