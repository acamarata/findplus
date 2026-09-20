"""Packaging bootstrap: GoogleFindMyTools resolves and lands on sys.path."""

from __future__ import annotations

import subprocess
import sys

from findplus.providers.findhub.bootstrap import ensure_gfmt_importable


def test_editable_mode_resolves_repo_path() -> None:
    resolved = ensure_gfmt_importable()
    assert resolved.name == "GoogleFindMyTools"
    assert resolved.is_dir()
    assert str(resolved) in sys.path


def test_idempotent() -> None:
    ensure_gfmt_importable()
    count = sys.path.count(str(ensure_gfmt_importable()))
    assert count == 1


def test_core_entry_modules_do_not_import_the_deprecated_findhub_shim() -> None:
    """`findplus.findhub` warns on import (see its docstring); the real modules
    must go through `findplus.providers.google_findhub` instead. `-W error`
    turns that warning into an ImportError if any of the three still resolve
    through the shim, which a plain `import findplus.api` would not catch
    (pytest already imported the package under test by then)."""
    result = subprocess.run(
        [
            sys.executable,
            "-W",
            "error::DeprecationWarning",
            "-c",
            "import findplus.api, findplus.poller, findplus.cli.main",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_chrome_patch_is_re_appliable_with_a_new_job_id(tmp_path, monkeypatch) -> None:
    """A second sign-in re-patches harmlessly, carrying the new job's closure.

    `_patch_vendor_chrome` deliberately has no `_ready` guard (unlike
    `ensure_gfmt_importable` above): the replacement create_driver closes over
    a job id, so a second sign-in needs the second job's closure, not the
    first's. What must stay true is that re-patching never restores the
    vendor's pkill'ing original or its blocking `input()`.
    """
    import types

    from findplus.config import get_settings
    from findplus.providers.google_findhub import browser

    vendor_chrome = types.ModuleType("chrome_driver")
    vendor_chrome.create_driver = lambda: "original"
    vendor_chrome.get_options = lambda: "options"
    auth_flow = types.ModuleType("Auth.auth_flow")
    auth_flow.input = input
    auth_pkg = types.ModuleType("Auth")
    auth_pkg.auth_flow = auth_flow
    monkeypatch.setitem(sys.modules, "chrome_driver", vendor_chrome)
    monkeypatch.setitem(sys.modules, "Auth", auth_pkg)
    monkeypatch.setitem(sys.modules, "Auth.auth_flow", auth_flow)
    monkeypatch.setattr(browser, "ensure_gfmt_importable", lambda: tmp_path)
    settings = get_settings(state_dir=tmp_path)

    browser._patch_vendor_chrome(settings, "job-idem")
    first = vendor_chrome.create_driver
    browser._patch_vendor_chrome(settings, "job-idem-2")
    second = vendor_chrome.create_driver

    assert first is not second
    assert second.__name__ == "_isolated_create_driver"
    assert auth_flow.input("x") == ""
